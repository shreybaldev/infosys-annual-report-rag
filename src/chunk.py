"""
Step 2: page-aware chunking with token overlap, across all docs in DOCS.

Strategy: one chunk per page of each doc. The page is the indivisible
retrieval unit (citations stay clean -- "see Infosys FY24 p. 47" is the
standard reference form in financial reporting). To handle sentences that
span page breaks, each chunk is prefixed with the last `OVERLAP_TOKENS` of
the previous *same-doc* page's text. Overlap never crosses doc boundaries.

Why page-based (not fixed-size sliding window):
  - Pages map 1:1 to citations in the rendered answer.
  - Most pages are 300-1500 tokens, well inside the embedding model's
    8192-token input limit.
  - Sliding-window chunks would fragment tables and section headers and
    require a separate (doc, page) locator at citation time.

Multi-doc:
  - Reads every per-doc parsed_<slug>.json file in DOCS order.
  - Chunk IDs are globally unique: "{slug}-p{page:03d}" e.g. "fy24-p047".
  - Each chunk carries source_doc_slug + source_doc_display for downstream
    citation rendering and Chroma metadata.

Input:  data/parsed_<slug>.json (one per Doc in src/docs.py)
Output: data/chunks.json        (combined across all docs)
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import tiktoken

from src.docs import DOCS, PROJECT_ROOT, chunks_json_path, parsed_json_path

# === Chunking config =======================================================
# 50 tokens of overlap from the previous same-doc page's tail. Chosen because:
#   - Long enough to capture a sentence or two crossing the page break.
#   - Short enough that it's <10% of an average page's token count, so we
#     barely inflate embedding cost.
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
    id: str                       # e.g. "fy24-p047" -- globally unique, sortable
    source_doc_slug: str          # "fy24" / "fy25"
    source_doc_display: str       # "Infosys FY24" / "Infosys FY25"
    page_number: int              # 1-indexed page within the source PDF
    text: str                     # composite_text from Step 1, prefixed with overlap
    char_count: int
    token_count: int
    overlap_prefix_tokens: int    # how many leading tokens are overlap from prev page


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


def _chunks_for_doc(parsed: dict, enc: tiktoken.Encoding, overlap_tokens: int) -> list[Chunk]:
    """Chunk one doc's parsed payload. Overlap stays within this doc."""
    src = parsed["source_doc"]
    slug = src["slug"]
    display = src["display"]

    out: list[Chunk] = []
    page_keys = sorted(parsed["pages"].keys(), key=int)
    prev_text = ""  # same-doc previous page's composite_text

    for key in page_keys:
        page = parsed["pages"][key]
        page_no = page["page_number"]
        text = (page.get("composite_text") or "").strip()

        if len(text) < MIN_CHARS_TO_CHUNK:
            # Skip blank / divider page. Don't update prev_text -- we want
            # the next real page to overlap with the last real page.
            continue

        overlap_prefix = _tail_tokens(prev_text, overlap_tokens, enc) if prev_text else ""
        combined = (overlap_prefix + "\n" + text) if overlap_prefix else text
        overlap_prefix_tok_count = len(enc.encode(overlap_prefix)) if overlap_prefix else 0
        token_count = len(enc.encode(combined))

        out.append(Chunk(
            id=f"{slug}-p{page_no:03d}",
            source_doc_slug=slug,
            source_doc_display=display,
            page_number=page_no,
            text=combined,
            char_count=len(combined),
            token_count=token_count,
            overlap_prefix_tokens=overlap_prefix_tok_count,
        ))
        prev_text = text

    return out


def build_chunks(overlap_tokens: int = OVERLAP_TOKENS) -> list[Chunk]:
    """Build chunks across every doc in DOCS that has a parsed file on disk."""
    enc = tiktoken.get_encoding(TOKENIZER_NAME)
    all_chunks: list[Chunk] = []
    for doc in DOCS:
        p = parsed_json_path(doc.slug)
        if not p.exists():
            print(f"[chunk] [{doc.slug}] SKIP -- no parsed file at {p.name} (run parse.py --doc {doc.slug})")
            continue
        parsed = json.loads(p.read_text(encoding="utf-8"))
        doc_chunks = _chunks_for_doc(parsed, enc, overlap_tokens)
        print(f"[chunk] [{doc.slug}] {len(doc_chunks)} chunks built")
        all_chunks.extend(doc_chunks)
    return all_chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk parsed-doc JSONs into a single chunks.json.")
    parser.add_argument("--overlap", type=int, default=OVERLAP_TOKENS,
                        help=f"Overlap tokens between adjacent same-doc pages (default {OVERLAP_TOKENS}).")
    args = parser.parse_args()

    out_path = chunks_json_path()
    print(f"[chunk] output -> {out_path}")
    t0 = time.time()
    chunks = build_chunks(overlap_tokens=args.overlap)
    elapsed = time.time() - t0

    if not chunks:
        raise SystemExit("[chunk] no chunks produced -- did parse.py run for any doc?")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "docs_included": sorted({c.source_doc_slug for c in chunks}),
        "chunk_strategy": {
            "type": "page_based",
            "overlap_tokens": args.overlap,
            "tokenizer": TOKENIZER_NAME,
            "min_chars_to_chunk": MIN_CHARS_TO_CHUNK,
        },
        "stats": {
            "n_chunks_total": len(chunks),
            "n_chunks_per_doc": {
                slug: sum(1 for c in chunks if c.source_doc_slug == slug)
                for slug in sorted({c.source_doc_slug for c in chunks})
            },
            "total_tokens": sum(c.token_count for c in chunks),
            "min_tokens": min(c.token_count for c in chunks),
            "max_tokens": max(c.token_count for c in chunks),
            "mean_tokens": sum(c.token_count for c in chunks) // len(chunks),
        },
        "chunks": [asdict(c) for c in chunks],
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    sz_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"[chunk] DONE in {elapsed:.1f}s")
    print(f"[chunk] wrote {out_path} ({sz_mb:.2f} MB)")
    print(f"[chunk] stats: {payload['stats']}")


if __name__ == "__main__":
    main()
