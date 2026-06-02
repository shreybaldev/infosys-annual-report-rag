"""
Step 5: retrieve -> assemble grounded context -> gpt-4o-mini -> answer with citations.

Pipeline
--------
  user query
    -> hybrid_retrieve(top-k chunks)
    -> render context block: "[Page N] {text}\n\n[Page M] {text}\n..."
    -> chat.completions.create(messages=[system+user], temperature=0)
    -> parse out cited page numbers
    -> return Answer dataclass

Grounding rules embedded in the system prompt
---------------------------------------------
1. Use ONLY the provided context.
2. Cite the page number for every claim, like "(p. 47)" or "(pp. 47, 49)".
3. If the context is insufficient, respond with the literal sentinel
   "INSUFFICIENT_CONTEXT: <reason>" so the UI can render an abstention.
4. No outside knowledge; no speculation.

Why a sentinel for abstention (rather than free-form refusal):
   We need a deterministic check downstream to flag abstentions in eval.
   A model that meanders into "Based on what's provided, it appears that..."
   when it shouldn't is the failure mode we're guarding against. The
   sentinel forces a yes/no decision the model has to make explicitly.

The cited-page parser (regex on the LLM output) is intentionally permissive:
matches "p. 47", "p 47", "pp. 47", "Page 47", and comma-separated runs like
"pp. 47, 49, 51". It captures plain integers in 1..page_count_max only;
out-of-range numbers in the text (e.g. dollar amounts) are filtered out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from openai import OpenAI

from src.retrieve import Hit, hybrid_retrieve

ANSWER_MODEL = "gpt-4o-mini"
ANSWER_TEMPERATURE = 0.0
ANSWER_MAX_TOKENS = 600
DEFAULT_TOP_K = 8                # context size; ~8 chunks * ~1000 tok = ~8K context tokens

# Sentinel the model uses to signal it cannot answer from context.
ABSTAIN_SENTINEL = "INSUFFICIENT_CONTEXT:"

# Cost trackers (gpt-4o-mini public pricing). Update if pricing changes.
ANSWER_COST_PER_1M_INPUT = 0.15
ANSWER_COST_PER_1M_OUTPUT = 0.60

SYSTEM_PROMPT = (
    "You are an analyst answering questions about Infosys's FY24 annual report.\n\n"
    "GROUNDING RULES (apply on every response):\n"
    "1. Use ONLY the provided context blocks below. Do not draw on outside knowledge\n"
    "   about Infosys or any general financial reasoning.\n"
    "2. Cite the page number for every factual claim in parentheses, like (p. 47)\n"
    "   or (pp. 47, 49) for multiple. The page number must come from a context\n"
    "   block actually used to make the claim.\n"
    "3. If the provided context does NOT contain enough information to answer,\n"
    f"   respond with exactly one line beginning '{ABSTAIN_SENTINEL}' followed by\n"
    "   a one-sentence explanation of what is missing. Do not attempt a partial\n"
    "   answer in that case.\n"
    "4. Be concise: 2-5 sentences for most questions. Use bullets only if the\n"
    "   user explicitly asks for a list.\n"
    "5. Quote numbers and proper nouns exactly as they appear in the context.\n"
)


@dataclass
class Answer:
    query: str
    text: str
    cited_pages: list[int]
    sources: list[Hit]              # everything retrieved, whether or not cited
    abstained: bool
    model: str
    mode: Literal["hybrid", "vector", "bm25"]
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0


# Permissive citation parser: matches p./pp./page/pages forms followed by ints.
# Strips out integers that aren't plausibly page numbers (we clip to <= 1000
# since the Infosys FY24 doc is 359 pages and we don't want to confuse
# dollar/year numbers with citations).
_CITE_PATTERN = re.compile(
    r"(?i)\b(?:p+\.?|pages?)\s*((?:\d{1,4})(?:\s*,\s*\d{1,4})*)"
)


def _parse_cited_pages(text: str, max_page: int = 1000) -> list[int]:
    """Extract unique page numbers cited in the LLM answer, in first-mention order."""
    seen: list[int] = []
    for m in _CITE_PATTERN.finditer(text):
        nums_str = m.group(1)
        for n_str in nums_str.split(","):
            try:
                n = int(n_str.strip())
            except ValueError:
                continue
            if 1 <= n <= max_page and n not in seen:
                seen.append(n)
    return seen


def _build_context_block(hits: list[Hit]) -> str:
    """Render retrieved chunks as a labeled context block. The "[Page N]" prefix
    is what the model anchors citations to -- keeping it visually distinct
    from the chunk body reduces the chance the model mistakes a number INSIDE
    the chunk text for the citation marker."""
    parts = []
    for h in hits:
        # Truncate very long chunks to keep total context under the model's
        # comfort zone. ~1500 chars ~= 350 tokens; for 8 hits that's ~3K context
        # tokens, well within gpt-4o-mini's 128K window but cheap and focused.
        snippet = h.text.strip()
        if len(snippet) > 1500:
            snippet = snippet[:1500] + "...[truncated]"
        parts.append(f"[Page {h.page_number}]\n{snippet}")
    return "\n\n".join(parts)


def answer(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    mode: Literal["hybrid", "vector", "bm25"] = "hybrid",
) -> Answer:
    """Retrieve -> LLM with grounding rules -> structured answer."""
    if mode == "hybrid":
        hits = hybrid_retrieve(query, k=top_k)
    elif mode == "vector":
        from src.retrieve import vector_retrieve
        hits = vector_retrieve(query, k=top_k)
    else:
        from src.retrieve import bm25_retrieve
        hits = bm25_retrieve(query, k=top_k)

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
    cited = [] if abstained else _parse_cited_pages(text)

    usage = resp.usage
    cost = ((usage.prompt_tokens / 1_000_000) * ANSWER_COST_PER_1M_INPUT
            + (usage.completion_tokens / 1_000_000) * ANSWER_COST_PER_1M_OUTPUT)

    return Answer(
        query=query,
        text=text,
        cited_pages=cited,
        sources=hits,
        abstained=abstained,
        model=ANSWER_MODEL,
        mode=mode,
        usage={
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        },
        cost_usd=round(cost, 5),
    )


# === CLI for quick spot-checks ============================================
#   python -m src.answer "What was operating margin in FY24"

def _cli() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Quick answer probe.")
    parser.add_argument("query", nargs="+")
    parser.add_argument("--k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--mode", choices=("hybrid", "vector", "bm25"), default="hybrid")
    args = parser.parse_args()
    q = " ".join(args.query)

    a = answer(q, top_k=args.k, mode=args.mode)
    print(f"query        : {q!r}")
    print(f"mode         : {a.mode} (top-{args.k})")
    print(f"abstained    : {a.abstained}")
    print(f"cited pages  : {a.cited_pages}")
    print(f"tokens       : {a.usage}  cost ~ ${a.cost_usd:.5f}")
    print(f"sources used (top {len(a.sources)}): {[h.page_number for h in a.sources]}")
    print("-" * 70)
    print(a.text)


if __name__ == "__main__":
    _cli()
