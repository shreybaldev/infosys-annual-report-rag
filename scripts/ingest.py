"""
One-shot rebuild pipeline: PDF -> parsed.json -> chunks.json -> chroma_db.

For local rebuilds and for the README's reproducibility story. Each step is
also runnable standalone via `python -m src.parse`, `python -m src.chunk`,
`python -m src.embed`.

Default behavior re-runs every step, regardless of whether intermediate
artifacts exist. The intermediate files (parsed.json, chunks.json) are
deterministic given the same PDF + same code, so re-running is safe and
keeps everything in lockstep. Use the per-step CLIs if you need finer
control (e.g. re-embed without re-parsing).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Add project root to sys.path so `from src import ...` works regardless of CWD.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src import parse, chunk, embed  # noqa: E402


def main() -> None:
    t0 = time.time()

    print("=" * 70)
    print("STEP 1/3: parse PDF -> data/parsed.json")
    print("=" * 70)
    parse.main()

    print("\n" + "=" * 70)
    print("STEP 2/3: chunk parsed.json -> data/chunks.json")
    print("=" * 70)
    # parse.main / chunk.main / embed.main read sys.argv; reset between steps
    # so each one sees only its own (default) args.
    sys.argv = [sys.argv[0]]
    chunk.main()

    print("\n" + "=" * 70)
    print("STEP 3/3: embed chunks.json -> chroma_db/")
    print("=" * 70)
    sys.argv = [sys.argv[0]]
    embed.main()

    elapsed = time.time() - t0
    print(f"\n[ingest] DONE in {elapsed:.1f}s total")


if __name__ == "__main__":
    main()
