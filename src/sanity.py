"""
Step 8: deterministic post-hoc checks on a generated Answer.

These run AFTER the LLM has produced its response. They catch failure
modes that the prompt alone cannot guarantee against, without requiring
another LLM call:

  1. citations_present     -- the answer must cite at least one (doc, page)
                              when not abstained.
  2. citations_grounded    -- every cited (doc, page) must appear in the
                              chunks actually retrieved. Catches hallucinated
                              citations where the model invents a page
                              number from thin air.
  3. citations_in_range    -- cited (doc, page) must be valid: doc slug must
                              exist in our corpus, page must be within that
                              doc's page count.
  4. no_meta_comments      -- soft warn on phrases like "based on the
                              provided context" that signal the model is
                              talking about the document rather than from it.

Status values:
  pass -- check passed cleanly
  warn -- soft signal, worth surfacing but not blocking
  fail -- hard signal, the answer is suspect

The UI renders fail/warn as small badges so the demo audience can SEE
that the system is actively checking itself. That visibility is the
point -- silent guardrails do not communicate care to a reviewer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Phrases the model sometimes emits when it leans on the prompt structure
# rather than the actual content. They aren't always bugs, but they're a
# tell that the answer may be lightly grounded.
META_COMMENT_PATTERNS = (
    "based on the provided context",
    "based on the context provided",
    "according to the context",
    "the provided context",
    "as per the document",
    "the document mentions",
    "the report states that",
    "from the information provided",
)

CheckStatus = Literal["pass", "warn", "fail"]


@dataclass
class SanityCheck:
    name: str
    status: CheckStatus
    detail: str


@dataclass
class SanityReport:
    checks: list[SanityCheck] = field(default_factory=list)
    has_failures: bool = False
    has_warnings: bool = False


def _fmt_cite(c: dict) -> str:
    return f"{c['doc_slug'].upper()}:p{c['page']}"


def run_checks(
    *,
    answer_text: str,
    abstained: bool,
    cited: list[dict],                 # [{"doc_slug": "fy24", "page": 47}, ...]
    source_keys: list[dict],           # same shape, from retrieved hits
    max_page_by_slug: dict[str, int],  # {"fy24": 296, "fy25": 359}
    known_doc_slugs: set[str],         # {"fy24", "fy25"}
) -> SanityReport:
    """Run all sanity checks on a multi-doc answer. Skips most checks if
    the answer was an abstention (no claims to verify in that case)."""
    checks: list[SanityCheck] = []

    if abstained:
        checks.append(SanityCheck(
            "abstention", "pass",
            "answer was an abstention; per-claim checks not applicable",
        ))
        return _summarize(checks)

    # 1) Citations must exist on a real answer.
    if not cited:
        checks.append(SanityCheck(
            "citations_present", "fail",
            "answer has no (doc, page) citations -- ungrounded claim",
        ))
    else:
        checks.append(SanityCheck(
            "citations_present", "pass",
            f"{len(cited)} citation(s)",
        ))

    # 2) Every cited (doc, page) must come from a retrieved source key.
    src_set = {(s["doc_slug"], s["page"]) for s in source_keys}
    ungrounded = [c for c in cited if (c["doc_slug"], c["page"]) not in src_set]
    if ungrounded:
        checks.append(SanityCheck(
            "citations_grounded", "fail",
            f"cited keys not in retrieved sources: {[_fmt_cite(c) for c in ungrounded]}",
        ))
    else:
        checks.append(SanityCheck(
            "citations_grounded", "pass",
            "all citations come from retrieved chunks",
        ))

    # 3) Doc slug must exist; page must be within that doc.
    out_of_range = []
    for c in cited:
        slug = c["doc_slug"]
        page = c["page"]
        if slug not in known_doc_slugs:
            out_of_range.append((c, f"unknown doc slug '{slug}'"))
            continue
        max_p = max_page_by_slug.get(slug, 0)
        if page < 1 or page > max_p:
            out_of_range.append((c, f"page {page} outside [1, {max_p}]"))
    if out_of_range:
        checks.append(SanityCheck(
            "citations_in_range", "fail",
            "; ".join(f"{_fmt_cite(c)} ({why})" for c, why in out_of_range),
        ))
    else:
        checks.append(SanityCheck(
            "citations_in_range", "pass",
            "all citations within valid doc/page ranges",
        ))

    # 4) Meta-comments -- warn, don't fail.
    lower = answer_text.lower()
    hits = [p for p in META_COMMENT_PATTERNS if p in lower]
    if hits:
        checks.append(SanityCheck(
            "no_meta_comments", "warn",
            f"meta-comment phrase(s) detected: {hits}",
        ))
    else:
        checks.append(SanityCheck(
            "no_meta_comments", "pass",
            "no meta-comment phrasing",
        ))

    return _summarize(checks)


def _summarize(checks: list[SanityCheck]) -> SanityReport:
    return SanityReport(
        checks=checks,
        has_failures=any(c.status == "fail" for c in checks),
        has_warnings=any(c.status == "warn" for c in checks),
    )
