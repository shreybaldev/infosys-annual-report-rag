"""
Step 8: deterministic post-hoc checks on a generated Answer.

These run AFTER the LLM has produced its response. They are *defensive* --
they catch failure modes that the prompt alone cannot guarantee against,
without requiring another LLM call:

  1. citations_present     -- the answer must cite at least one page
                              (skipped if the model abstained).
  2. citations_grounded    -- every cited page must appear in the chunks
                              actually retrieved. Catches hallucinated
                              citations where the model invents a page
                              number from thin air.
  3. citations_in_range    -- cited pages must be 1..max_page. Catches
                              numbers from the body text being mis-parsed
                              as citations.
  4. no_meta_comments      -- flags phrases like "based on the provided
                              context" that signal the model is talking
                              about the document rather than from it.

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


def run_checks(
    *,
    answer_text: str,
    abstained: bool,
    cited_pages: list[int],
    source_pages: list[int],
    max_page: int,
) -> SanityReport:
    """Run all sanity checks. Skips most checks if the answer was an
    abstention (no claims to verify in that case)."""
    checks: list[SanityCheck] = []

    if abstained:
        checks.append(SanityCheck(
            "abstention", "pass",
            "answer was an abstention; per-claim checks not applicable",
        ))
        return _summarize(checks)

    # 1) Citations must exist on a real answer.
    if not cited_pages:
        checks.append(SanityCheck(
            "citations_present", "fail",
            "answer has no page citations -- ungrounded claim",
        ))
    else:
        checks.append(SanityCheck(
            "citations_present", "pass",
            f"{len(cited_pages)} page citation(s)",
        ))

    # 2) Every cited page must come from a retrieved source.
    src_set = set(source_pages)
    ungrounded = [p for p in cited_pages if p not in src_set]
    if ungrounded:
        checks.append(SanityCheck(
            "citations_grounded", "fail",
            f"cited pages not in retrieved sources: {ungrounded}",
        ))
    else:
        checks.append(SanityCheck(
            "citations_grounded", "pass",
            "all citations come from retrieved chunks",
        ))

    # 3) Page numbers must be within the document.
    out_of_range = [p for p in cited_pages if p < 1 or p > max_page]
    if out_of_range:
        checks.append(SanityCheck(
            "citations_in_range", "fail",
            f"cited page(s) outside [1, {max_page}]: {out_of_range}",
        ))
    else:
        checks.append(SanityCheck(
            "citations_in_range", "pass",
            f"all citations within [1, {max_page}]",
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
