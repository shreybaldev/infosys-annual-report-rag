"""
Step 2: page-aware chunking with token overlap.

Strategy: one chunk per page. The page is the indivisible retrieval unit
(citations stay clean -- "see page 47" is the standard reference form in
financial reporting). To handle sentences that span the page break, each
chunk is prefixed with the last `OVERLAP_TOKENS` of the *previous* page's
text. The overlap is invisible to citation logic (the chunk is still tagged
to the current page) but preserves cross-page context for embedding.

Why page-based (not fixed-size sliding window):
  - Pages map 1:1 to citations in the rendered answer. A user clicking a
    source goes to a real, locatable place in the PDF.
  - Many pages in this doc are 300-800 tokens, comfortably inside the
    text-embedding-3-small per-input limit. The largest pages we saw
    (~2,000 tokens) still fit easily.
  - Sliding-window chunks would fragment tables and section headers and
    require a separate page-locator at citation time.

Known limitation (documented in README):
  - Long pages (>~1,500 tokens) are not subdivided. A v2 would split inside
    the page on paragraph boundaries. For v1 this trades a small amount of
    retrieval precision for clean citation semantics.

Input:  data/parsed.json   (from Step 1)
Output: data/chunks.json   (committed; consumed by Step 3 embedder)
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import tiktoken

# === Paths =================================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARSED_PATH = PROJECT_ROOT / "data" / "parsed.json"
OUT_PATH = PROJECT_ROOT / "data" / "chunks.json"

# === Chunking config =======================================================
# 50 tokens of overlap from the previous page's tail. Chosen because:
#   - Long enough to capture a sentence or two crossing the page break.
#   - Short enough that it's <10% of an average page's token count, so we
#     barely inflate embedding cost.
# Source of the convention: standard RAG practice (50-100 tokens is common).
OVERLAP_TOKENS = 50

# cl100k_base is the tokenizer used by text-embedding-3-small. Using the
# same tokenizer for our counts means the "token_count" in chunks.json is
# what the embedding API will actually see.
TOKENIZER_NAME = "cl100k_base"

# Pages with less than this many characters are considered blank/divider
# pages and skipped. Avoids embedding garbage like a lone page number.
MIN_CHARS_TO_CHUNK = 30


@dataclass
class Chunk:
    id: str                       # e.g. "p047" -- stable, page-derived
    page_number: int              # 1-indexed page in the source PDF
    text: str                     # composite_text from Step 1, prefixed with overlap
    char_count: int               # length of `text` (incl. overlap prefix)
    token_count: int              # cl100k_base token count of `text`
    overlap_prefix_tokens: int    # how many of the leading tokens are overlap from prev page


def _tail_tokens(text: str, n: int, enc: tiktoken.Encoding) -> str:
    """Return the textual tail of `text` corresponding to its last n tokens.
    We round-trip through the tokenizer so the overlap is measured in tokens
    (model units) rather than chars (which would vary wildly with word length)."""
    if not text:
        return ""
    tokens = enc.encode(text)
    if len(tokens) <= n:
        return text
    return enc.decode(tokens[-n:])


def build_chunks(parsed: dict, overlap_tokens: int = OVERLAP_TOKENS) -> list[Chunk]:
    """Walk pages in numeric order, build one Chunk per non-empty page,
    carrying a token-bounded overlap from the previous page's text."""
    enc = tiktoken.get_encoding(TOKENIZER_NAME)
    chunks: list[Chunk] = []

    # Iterate pages in numeric order. JSON-loaded dict keys may not preserve
    # insertion order across all callers, so sort defensively.
    page_keys = sorted(parsed["pages"].keys(), key=int)
    prev_text = ""  # composite_text of the previous *kept* page

    for key in page_keys:
        page = parsed["pages"][key]
        page_no = page["page_number"]
        text = (page.get("composite_text") or "").strip()

        if len(text) < MIN_CHARS_TO_CHUNK:
            # Skip blank / divider page. We do NOT update prev_text -- we
            # want the next real page to overlap with the last real page,
            # not with a blank one.
            continue

        overlap_prefix = _tail_tokens(prev_text, overlap_tokens, enc) if prev_text else ""
        # Single newline between overlap and current text is enough to mark
        # the boundary; a heavier separator would skew embedding semantics.
        combined = (overlap_prefix + "\n" + text) if overlap_prefix else text
        overlap_prefix_tok_count = len(enc.encode(overlap_prefix)) if overlap_prefix else 0
        token_count = len(enc.encode(combined))

        chunks.append(Chunk(
            id=f"p{page_no:03d}",         # zero-padded so lexical sort == page-number sort
            page_number=page_no,
            text=combined,
            char_count=len(combined),
            token_count=token_count,
            overlap_prefix_tokens=overlap_prefix_tok_count,
        ))
        prev_text = text  # update only for kept (non-blank) pages

    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk parsed.json into chunks.json.")
    parser.add_argument("--in", dest="in_path", type=Path, default=PARSED_PATH)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument("--overlap", type=int, default=OVERLAP_TOKENS,
                        help=f"Overlap tokens between adjacent pages (default {OVERLAP_TOKENS}).")
    args = parser.parse_args()

    if not args.in_path.exists():
        raise SystemExit(f"[chunk] missing input {args.in_path}. Run src/parse.py first.")

    print(f"[chunk] input  -> {args.in_path}")
    print(f"[chunk] output -> {args.out}")
    t0 = time.time()
    parsed = json.loads(args.in_path.read_text(encoding="utf-8"))
    chunks = build_chunks(parsed, overlap_tokens=args.overlap)
    elapsed = time.time() - t0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": str(args.in_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "chunk_strategy": {
            "type": "page_based",
            "overlap_tokens": args.overlap,
            "tokenizer": TOKENIZER_NAME,
            "min_chars_to_chunk": MIN_CHARS_TO_CHUNK,
        },
        "stats": {
            "n_chunks": len(chunks),
            "n_pages_in_source": parsed["page_count_parsed"],
            "total_tokens": sum(c.token_count for c in chunks),
            "min_tokens": min((c.token_count for c in chunks), default=0),
            "max_tokens": max((c.token_count for c in chunks), default=0),
            "mean_tokens": (sum(c.token_count for c in chunks) // max(len(chunks), 1)),
        },
        "chunks": [asdict(c) for c in chunks],
    }
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    sz_mb = args.out.stat().st_size / (1024 * 1024)
    print(f"[chunk] DONE in {elapsed:.1f}s")
    print(f"[chunk] wrote {args.out} ({sz_mb:.2f} MB)")
    print(f"[chunk] stats: {payload['stats']}")


if __name__ == "__main__":
    main()
