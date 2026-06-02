"""
Step 5: retrieve -> assemble grounded context -> gpt-4o-mini -> answer with citations.

Multi-doc note
--------------
Every citation now identifies BOTH the document AND the page, since the
corpus spans multiple annual reports (currently FY24 and FY25). Citation
format: (FY24, p. 47) or (FY24, pp. 47, 49) or (FY24, p. 47; FY25, p. 50)
when the model is comparing across reports.

Pipeline
--------
  user query (+ optional doc filter)
    -> hybrid_retrieve(top-k chunks)
    -> render context block: "[FY24 · Page 47] {text}\n\n[FY25 · Page 50] {text}\n..."
    -> chat.completions.create(messages=[system+user], temperature=0)
    -> parse out cited (doc, page) tuples
    -> return Answer dataclass

Why a sentinel for abstention (rather than free-form refusal):
   We need a deterministic check downstream to flag abstentions in eval.
   A model that meanders into "Based on what's provided, it appears that..."
   when it shouldn't is the failure mode we're guarding against. The
   sentinel forces a yes/no decision the model has to make explicitly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from openai import OpenAI

from src.docs import DOCS, DOCS_BY_SLUG
from src.retrieve import Hit, hybrid_retrieve
from src.sanity import SanityReport, run_checks

# Per-doc max page counts derived from the parsed PDFs. Used by sanity to
# verify cited pages are in-range for the cited doc. Lives here (not in
# sanity.py) so sanity stays corpus-agnostic. Update if a new doc is added
# (or just regenerate from data/parsed_<slug>.json).
MAX_PAGE_BY_SLUG: dict[str, int] = {
    "fy24": 296,
    "fy25": 359,
}

ANSWER_MODEL = "gpt-4o-mini"
ANSWER_TEMPERATURE = 0.0
ANSWER_MAX_TOKENS = 600
DEFAULT_TOP_K = 12               # ~12 chunks * ~1000 tok = ~12K context tokens. Bumped from 8
                                 # when the corpus moved to multi-doc: with 2 docs sharing
                                 # the same top-k budget, per-doc retrieval depth halves.
                                 # 12 gives roughly 6 chunks per doc, comparable to the
                                 # single-doc 8 we originally tuned for.

# Sentinel the model uses to signal it cannot answer from context.
ABSTAIN_SENTINEL = "INSUFFICIENT_CONTEXT:"

# Cost trackers (gpt-4o-mini public pricing). Update if pricing changes.
ANSWER_COST_PER_1M_INPUT = 0.15
ANSWER_COST_PER_1M_OUTPUT = 0.60

# Build the cite-format examples dynamically from the live DOC slugs so a
# future doc add doesn't require touching the prompt copy.
_SLUG_EXAMPLE = DOCS[0].slug.upper() if DOCS else "FY24"
_SLUG_EXAMPLE_2 = DOCS[1].slug.upper() if len(DOCS) > 1 else _SLUG_EXAMPLE

SYSTEM_PROMPT = (
    "You are an analyst answering questions about Infosys's annual reports.\n"
    f"The corpus currently includes: {', '.join(d.display for d in DOCS)}.\n\n"
    "GROUNDING RULES (these are hard; do not relax them for style reasons):\n"
    "1. Use ONLY the provided context blocks below. Do not draw on outside\n"
    "   knowledge about Infosys, the industry, or general financial reasoning.\n"
    "2. Cite the SOURCE DOC and page number for every factual claim. Format:\n"
    f"   ({_SLUG_EXAMPLE}, p. 47) for one page, ({_SLUG_EXAMPLE}, pp. 47, 49)\n"
    f"   for multiple pages in the same doc, or\n"
    f"   ({_SLUG_EXAMPLE}, p. 47; {_SLUG_EXAMPLE_2}, p. 50) when comparing\n"
    "   across docs. Each citation must come from a context block you used.\n"
    "3. If the context does not contain enough information to answer,\n"
    f"   respond with exactly one line beginning '{ABSTAIN_SENTINEL}' followed\n"
    "   by a one-sentence explanation of what is missing. Do not attempt a\n"
    "   partial answer in that case.\n"
    "4. Quote numbers, names, and other specifics exactly as they appear in\n"
    "   the context.\n"
    "5. When the user asks about ONE year, answer from that year's doc only.\n"
    "   When the user asks a trend/compare question, draw on multiple docs\n"
    "   and attribute each fact to its source.\n\n"
    "STYLE (write naturally; let the question shape the length):\n"
    "- A direct yes/no or single-fact question gets one or two sentences.\n"
    "- A 'summarize' or 'explain' question gets a short paragraph (typically\n"
    "  3-6 sentences). A 'compare' or 'list' question can use a brief\n"
    "  bulleted list if that reads more clearly than prose.\n"
    "- Sound like a colleague who knows the documents well, not like a legal\n"
    "  disclosure. Plain language. Don't echo the question back. Don't\n"
    "  preface with 'based on the provided context' or 'the document states\n"
    "  that' -- just answer.\n"
    "- Place citations at the end of the clause they support, not bolted on\n"
    "  at the end of a paragraph. Combine cites when several facts in one\n"
    "  sentence come from the same doc: 'Revenue grew to X while margins\n"
    f"  expanded to Y ({_SLUG_EXAMPLE}, pp. 47, 49).'\n"
)


@dataclass
class Citation:
    doc_slug: str        # e.g. "fy24"
    page: int            # 1-indexed within that doc

    def as_dict(self) -> dict:
        return {"doc_slug": self.doc_slug, "page": self.page}


@dataclass
class Answer:
    query: str
    text: str
    cited: list[Citation]          # parsed (doc, page) citations
    sources: list[Hit]             # everything retrieved, whether or not cited
    abstained: bool
    model: str
    mode: Literal["hybrid", "vector", "bm25"]
    doc_slugs_filter: list[str] | None = None  # None = all docs
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    sanity: SanityReport | None = None

    # Convenience back-compat-ish helpers for the UI / eval layer.
    @property
    def cited_pages(self) -> list[int]:
        """All cited page numbers, regardless of doc. Used by older code paths
        that pre-date multi-doc and just want a flat list."""
        return [c.page for c in self.cited]


# Citation regex. Matches one citation group like "FY24, p. 47" or
# "FY24, pp. 47, 49". A single answer can contain multiple groups separated
# by ";" or in separate parentheses; we run the regex globally.
#
# Group 1 = doc slug (case-insensitive, e.g. "FY24")
# Group 2 = page-list (e.g. "47" or "47, 49, 51")
#
# Bounded {1,4} on the page digits so we don't pick up dollar amounts or
# years like (2024) embedded in normal prose.
_CITE_PATTERN = re.compile(
    r"(?i)\b(?P<doc>FY\d{2})\s*,\s*p+\.?\s*(?P<pages>\d{1,4}(?:\s*,\s*\d{1,4})*)"
)


def _parse_citations(text: str) -> list[Citation]:
    """Extract unique (doc_slug, page) citations in first-mention order."""
    seen: set[tuple[str, int]] = set()
    out: list[Citation] = []
    for m in _CITE_PATTERN.finditer(text):
        slug = m.group("doc").lower()
        for n_str in m.group("pages").split(","):
            try:
                page = int(n_str.strip())
            except ValueError:
                continue
            key = (slug, page)
            if key in seen:
                continue
            seen.add(key)
            out.append(Citation(doc_slug=slug, page=page))
    return out


def _build_context_block(hits: list[Hit]) -> str:
    """Render retrieved chunks as a labeled context block.
    Prefix format: "[FY24 · Page 47]" -- visually distinct so the model
    anchors citations to it rather than to numbers inside the chunk body."""
    parts = []
    for h in hits:
        snippet = h.text.strip()
        if len(snippet) > 1500:
            # Cap individual chunk length so a few outlier-long pages don't
            # crowd out other relevant ones. ~1500 chars ~= 350 tokens.
            snippet = snippet[:1500] + "...[truncated]"
        # Use the slug in uppercase to match the cite format the model
        # produces (e.g. "FY24"), keeping prompt + cite vocabulary aligned.
        parts.append(f"[{h.source_doc_slug.upper()} · Page {h.page_number}]\n{snippet}")
    return "\n\n".join(parts)


def answer(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    mode: Literal["hybrid", "vector", "bm25"] = "hybrid",
    doc_slugs: list[str] | None = None,
) -> Answer:
    """Retrieve -> LLM with grounding rules -> structured answer.
    Optional doc_slugs filter restricts retrieval to a subset of the corpus."""
    if mode == "hybrid":
        hits = hybrid_retrieve(query, k=top_k, doc_slugs=doc_slugs)
    elif mode == "vector":
        from src.retrieve import vector_retrieve
        hits = vector_retrieve(query, k=top_k, doc_slugs=doc_slugs)
    else:
        from src.retrieve import bm25_retrieve
        hits = bm25_retrieve(query, k=top_k, doc_slugs=doc_slugs)

    context = _build_context_block(hits)
    user_msg = f"CONTEXT:\n\n{context}\n\n---\n\nQUESTION: {query}"

    client = OpenAI()
    resp = client.chat.completions.create(
        model=ANSWER_MODEL,
        temperature=ANSWER_TEMPERATURE,
        max_tokens=ANSWER_MAX_TOKENS,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    )
    text = (resp.choices[0].message.content or "").strip()
    abstained = text.lstrip().startswith(ABSTAIN_SENTINEL)
    cited = [] if abstained else _parse_citations(text)

    usage = resp.usage
    cost = ((usage.prompt_tokens / 1_000_000) * ANSWER_COST_PER_1M_INPUT
            + (usage.completion_tokens / 1_000_000) * ANSWER_COST_PER_1M_OUTPUT)

    sanity_report = run_checks(
        answer_text=text,
        abstained=abstained,
        cited=[c.as_dict() for c in cited],
        source_keys=[{"doc_slug": h.source_doc_slug, "page": h.page_number} for h in hits],
        max_page_by_slug=MAX_PAGE_BY_SLUG,
        known_doc_slugs=set(DOCS_BY_SLUG),
    )

    return Answer(
        query=query,
        text=text,
        cited=cited,
        sources=hits,
        abstained=abstained,
        model=ANSWER_MODEL,
        mode=mode,
        doc_slugs_filter=doc_slugs,
        usage={
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        },
        cost_usd=round(cost, 5),
        sanity=sanity_report,
    )


# === CLI for quick spot-checks ============================================
#   python -m src.answer "How did revenue change from FY24 to FY25"

def _cli() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Quick answer probe.")
    parser.add_argument("query", nargs="+")
    parser.add_argument("--k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--mode", choices=("hybrid", "vector", "bm25"), default="hybrid")
    parser.add_argument("--doc", action="append", default=None,
                        help="Restrict to a doc slug; repeatable. Default = all docs.")
    args = parser.parse_args()
    q = " ".join(args.query)

    a = answer(q, top_k=args.k, mode=args.mode, doc_slugs=args.doc)
    print(f"query        : {q!r}")
    print(f"mode         : {a.mode} (top-{args.k}, docs={a.doc_slugs_filter or 'all'})")
    print(f"abstained    : {a.abstained}")
    print(f"cited        : {[(c.doc_slug, c.page) for c in a.cited]}")
    print(f"tokens       : {a.usage}  cost ~ ${a.cost_usd:.5f}")
    print(f"sources used : {[(h.source_doc_slug, h.page_number) for h in a.sources]}")
    print("-" * 70)
    print(a.text)


if __name__ == "__main__":
    _cli()
