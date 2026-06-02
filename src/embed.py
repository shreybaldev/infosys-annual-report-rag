"""
Step 3a: chunks -> OpenAI embeddings -> persistent ChromaDB collection.

Pipeline
--------
  data/chunks.json --[batches of N]--> OpenAI text-embedding-3-small
                                       --> chroma_db/  (collection: infosys_ar)

Design notes
------------
- Model: text-embedding-3-small (1536-dim). Chosen for cost/quality balance:
  ~$0.02 / 1M tokens, materially cheaper than text-embedding-3-large with
  small recall drop on retrieval tasks. For a 350K-token corpus this is
  ~$0.007 per full rebuild.

- Batching: 100 chunks per request. OpenAI's per-request limit is 2048 inputs
  / ~300K tokens; 100 is well inside both bounds and gives us a clean
  progress signal (1 progress line per ~3 batches).

- Cosine distance: text-embedding-3-small returns L2-normalized vectors, so
  cosine == dot product. We tell Chroma 'hnsw:space=cosine' for clarity
  and to ensure stored distances are interpretable as 1-cosine_similarity.

- Idempotent rebuild: on every run we DELETE the existing 'infosys_ar'
  collection and recreate it. Embeddings are deterministic for a given
  model/input, so rebuilds reproduce identically. Cheaper and simpler than
  diff-based updates for a corpus this size.

- Streamlit Cloud sqlite shim: Chroma needs sqlite >= 3.35. Streamlit Cloud
  ships an older system sqlite, so on Linux we swap in pysqlite3-binary
  (installed conditionally in requirements.txt). On Windows the shim is a
  no-op (we just trust the system sqlite).
"""

from __future__ import annotations

# --- sqlite shim, must happen BEFORE 'import chromadb' on Streamlit Cloud ---
try:
    __import__("pysqlite3")
    import sys as _sys
    _sys.modules["sqlite3"] = _sys.modules["pysqlite3"]
except ImportError:
    pass  # Windows local dev: system sqlite is recent enough.
# ----------------------------------------------------------------------------

import argparse
import json
import time
from pathlib import Path

import chromadb
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHUNKS_PATH = PROJECT_ROOT / "data" / "chunks.json"
CHROMA_DIR = PROJECT_ROOT / "chroma_db"

COLLECTION_NAME = "infosys_ar"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536           # what text-embedding-3-small returns by default
BATCH_SIZE = 100               # chunks per OpenAI embeddings request

# Public pricing for the running cost estimate. Update if pricing changes.
COST_PER_1M_TOKENS_USD = 0.02


def _embed_batch(client: OpenAI, texts: list[str]) -> tuple[list[list[float]], int]:
    """One OpenAI embeddings request. Returns (vectors, prompt_tokens)."""
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    vectors = [d.embedding for d in resp.data]
    return vectors, resp.usage.prompt_tokens


def build_index(
    chunks_path: Path = CHUNKS_PATH,
    chroma_dir: Path = CHROMA_DIR,
    batch_size: int = BATCH_SIZE,
) -> dict:
    """Load chunks.json, embed in batches, persist to Chroma. Returns stats."""
    if not chunks_path.exists():
        raise SystemExit(f"[embed] missing {chunks_path}. Run src/chunk.py first.")

    payload = json.loads(chunks_path.read_text(encoding="utf-8"))
    chunks = payload["chunks"]
    print(f"[embed] {len(chunks)} chunks loaded from {chunks_path.name}")

    # PersistentClient writes to a SQLite-backed dir; safe to commit to git.
    chroma_dir.mkdir(parents=True, exist_ok=True)
    client_chroma = chromadb.PersistentClient(path=str(chroma_dir))

    # Idempotent rebuild: drop existing collection if present.
    existing = [c.name for c in client_chroma.list_collections()]
    if COLLECTION_NAME in existing:
        print(f"[embed] dropping existing collection '{COLLECTION_NAME}'")
        client_chroma.delete_collection(COLLECTION_NAME)
    collection = client_chroma.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},  # see module docstring
    )

    client_oai = OpenAI()
    total_tokens = 0
    n_batches = (len(chunks) + batch_size - 1) // batch_size
    t0 = time.time()

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c["text"] for c in batch]
        vectors, used = _embed_batch(client_oai, texts)
        total_tokens += used

        # Chroma metadata values must be primitive types (str, int, float, bool).
        # We store the page number (for citations) and token count (for debugging).
        ids = [c["id"] for c in batch]
        metadatas = [
            {"page_number": int(c["page_number"]), "token_count": int(c["token_count"])}
            for c in batch
        ]
        collection.add(ids=ids, embeddings=vectors, documents=texts, metadatas=metadatas)

        batch_no = i // batch_size + 1
        est_cost = (total_tokens / 1_000_000) * COST_PER_1M_TOKENS_USD
        print(
            f"[embed] batch {batch_no}/{n_batches}  "
            f"+{len(batch)} chunks, +{used:,} tokens  "
            f"| cumulative: {total_tokens:,} tokens, ~${est_cost:.4f}"
        )

    elapsed = time.time() - t0
    stats = {
        "collection": COLLECTION_NAME,
        "n_chunks_indexed": collection.count(),
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dim": EMBEDDING_DIM,
        "total_input_tokens": total_tokens,
        "cost_usd_estimate": round((total_tokens / 1_000_000) * COST_PER_1M_TOKENS_USD, 4),
        "elapsed_s": round(elapsed, 1),
        "chroma_dir": str(chroma_dir.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    }
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed chunks.json into ChromaDB.")
    parser.add_argument("--in", dest="in_path", type=Path, default=CHUNKS_PATH)
    parser.add_argument("--chroma-dir", type=Path, default=CHROMA_DIR)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args()

    print(f"[embed] input  -> {args.in_path}")
    print(f"[embed] chroma -> {args.chroma_dir}")
    stats = build_index(args.in_path, args.chroma_dir, args.batch_size)
    print(f"\n[embed] DONE")
    print(f"[embed] {stats}")


if __name__ == "__main__":
    main()
