"""
Single source of truth for the corpus.

Every other module reads DOCS from here -- adding a new annual report is a
one-line change in this file plus a parse + chunk + embed run.

Each Doc carries:
  slug    : short stable id used in chunk IDs, citations, and Chroma metadata
            (must be filesystem-safe and citation-readable, e.g. "fy24")
  display : human-friendly label rendered in the UI and in answer citations
            (e.g. "Infosys FY24")
  path    : PDF path on disk, anchored off PROJECT_ROOT
  fiscal_year_ending : ISO date for the fiscal year the report covers;
            stored so the UI / README can show authoritative dates and so
            the answer-layer knows which year is "more recent".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Doc:
    slug: str
    display: str
    path: Path
    fiscal_year_ending: str  # ISO 8601 date string (YYYY-MM-DD)


DOCS: tuple[Doc, ...] = (
    Doc(
        slug="fy24",
        display="Infosys FY24",
        path=PROJECT_ROOT / "data" / "infosys_ar_fy24.pdf",
        fiscal_year_ending="2024-03-31",
    ),
    Doc(
        slug="fy25",
        display="Infosys FY25",
        path=PROJECT_ROOT / "data" / "infosys_ar_fy25.pdf",
        fiscal_year_ending="2025-03-31",
    ),
)

DOCS_BY_SLUG: dict[str, Doc] = {d.slug: d for d in DOCS}


def parsed_json_path(slug: str) -> Path:
    """Where parse.py writes per-doc parsed output."""
    return PROJECT_ROOT / "data" / f"parsed_{slug}.json"


def chunks_json_path() -> Path:
    """Single combined chunks file across all docs."""
    return PROJECT_ROOT / "data" / "chunks.json"


def chroma_dir() -> Path:
    return PROJECT_ROOT / "chroma_db"


COLLECTION_NAME = "infosys_ar"  # one collection across all docs; filter via metadata
