"""
One-shot rebuild pipeline: PDFs -> parsed_<slug>.json -> chunks.json -> chroma_db.

For local rebuilds and for the README's reproducibility story. Each step is
also runnable standalone:
  python -m src.parse                 # all docs
  python -m src.parse --doc fy24      # just one
  python -m src.chunk
  python -m src.embed

Default behavior re-runs every step. Per-doc parsed files are
deterministic given the same PDF + same code, so re-running is safe and
keeps everything in lockstep across all docs in DOCS.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Add project root to sys.path so `from src import ...` works regardless of CWD.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src import parse, chunk, embed  # noqa: E402
from src.docs import DOCS  # noqa: E402


def main() -> None:
    t0 = time.time()

    print("=" * 70)
    print(f"STEP 1/3: parse {len(DOCS)} PDF(s) -> data/parsed_<slug>.json")
    print("=" * 70)
    # parse.main reads sys.argv; reset so it sees only its own (default) args
    # and processes every doc in DOCS.
    sys.argv = [sys.argv[0]]
    parse.main()

    print("\n" + "=" * 70)
    print("STEP 2/3: chunk parsed_*.json -> data/chunks.json (combined)")
    print("=" * 70)
    sys.argv = [sys.argv[0]]
    chunk.main()

    print("\n" + "=" * 70)
    print("STEP 3/3: embed chunks.json -> chroma_db/")
    print("=" * 70)
    sys.argv = [sys.argv[0]]
    embed.main()

    elapsed = time.time() - t0
    print(f"\n[ingest] DONE in {elapsed:.1f}s total across {len(DOCS)} doc(s)")


if __name__ == "__main__":
    main()
