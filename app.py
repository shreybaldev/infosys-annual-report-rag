"""
Streamlit UI for the Infosys FY24 hybrid-search RAG.

Single-file entry point used both locally (`streamlit run app.py`) and on
Streamlit Community Cloud. We deliberately keep this thin and stateless --
all the heavy lifting (retrieve, answer, sanity) lives in src/.

Two things the UI layer owns that the library code does NOT:
  1. Bridging Streamlit's `st.secrets` into `os.environ` so that the
     OpenAI() clients inside src/ work transparently on both the local
     dev environment (env var) and Streamlit Cloud (secrets UI).
  2. Caching the expensive bootstrap (Chroma + BM25 + OpenAI client) via
     @st.cache_resource so retrieval is fast across reruns.
"""

from __future__ import annotations

import os

# Force pure-Python protobuf BEFORE any other import. Streamlit Cloud's
# installed protobuf >=5 enforces a new descriptor API that opentelemetry-
# proto's generated code (pulled in by chromadb 0.6.x) does not satisfy,
# causing _CheckCalledFromGeneratedFile to fail at import time. The pure-
# Python impl skips that check. Local Windows dev never hit this because
# we had a compatible protobuf installed; only manifested on Cloud.
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import time

import streamlit as st

# --- secrets bridging: must happen BEFORE importing src.* (which constructs
#     OpenAI() lazily but configures itself from os.environ at call time). ---
# On Streamlit Cloud, the key lives in st.secrets after you paste it into
# the Settings -> Secrets UI. On local dev, you set OPENAI_API_KEY in your
# shell env (or .streamlit/secrets.toml). Bridging makes both paths work.
if "OPENAI_API_KEY" not in os.environ:
    try:
        if "OPENAI_API_KEY" in st.secrets:
            os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        pass

from src.answer import answer, ABSTAIN_SENTINEL  # noqa: E402
from src.docs import DOCS  # noqa: E402
from src.retrieve import (  # noqa: E402  -- imported to warm the lazy singletons
    _get_chroma_collection, _get_bm25, _get_openai,
)


# === Page config ==========================================================
st.set_page_config(
    page_title="Infosys FY24 RAG",
    page_icon=None,          # default; no emoji
    layout="wide",
)


# === Cached bootstrap =====================================================
# @st.cache_resource holds shared, cross-session singletons (vs.
# @st.cache_data which is per-input). Chroma + BM25 + OpenAI client are
# exactly the "build once, reuse forever" case cache_resource exists for.
@st.cache_resource(show_spinner="Warming up retrievers...")
def _warmup() -> dict:
    """Force-instantiate the lazy singletons in src.retrieve so the first
    user query doesn't pay BM25-index-build cost (~1s for 359 docs)."""
    coll = _get_chroma_collection()
    bm25, chunks = _get_bm25()
    _ = _get_openai()
    return {"n_chunks": coll.count(), "bm25_docs": len(chunks)}


# === Sidebar: about + canned examples + mode toggle =======================
EXAMPLE_QUESTIONS = [
    # Cross-doc / trend questions -- demonstrate the multi-year capability.
    "How did Infosys's total employee count change from FY24 to FY25?",
    "Compare Infosys's AI/Topaz strategy across FY24 and FY25.",
    # Single-doc factual / synthesis.
    "Who is the CEO of Infosys, and what is their background?",
    "What are the main competitive and regulatory risks Infosys discloses?",
    "How does Infosys describe its approach to ESG and net-zero commitments?",
    # Abstention test -- should respond with INSUFFICIENT_CONTEXT, not a guess.
    "What was the price of Bitcoin in January 2024?",
]

with st.sidebar:
    st.markdown("### Infosys Annual Report RAG")
    docs_label = " + ".join(d.display.replace("Infosys ", "") for d in DOCS)
    st.caption(
        f"Hybrid vector + BM25 retrieval over **{docs_label}**, fused with RRF. "
        "gpt-4o-mini answers with per-document page citations. Portfolio piece."
    )
    st.divider()
    st.markdown("**Try a question:**")
    # Buttons (not radio) so the chosen example flows into st.session_state
    # immediately, while still letting the user type a custom question after.
    for q in EXAMPLE_QUESTIONS:
        if st.button(q, use_container_width=True, key=f"ex_{hash(q)}"):
            st.session_state["query_input"] = q
    st.divider()
    # Doc filter -- "All docs" by default lets the LLM compare across years.
    # Single-doc selection narrows retrieval, useful for "answer using only FY24".
    doc_filter_options = ["All docs"] + [d.display for d in DOCS]
    doc_filter_label = st.radio(
        "Limit retrieval to",
        options=doc_filter_options,
        index=0,
        help="Default: all docs. Pick a single year to force the model to "
             "answer only from that report (useful for comparison checks).",
    )
    if doc_filter_label == "All docs":
        doc_slugs_filter: list[str] | None = None
    else:
        # Reverse-lookup display -> slug; one-element list since radio is single-select.
        doc_slugs_filter = [d.slug for d in DOCS if d.display == doc_filter_label]
    mode = st.radio(
        "Retrieval mode",
        options=["hybrid", "vector", "bm25"],
        index=0,
        help=(
            "hybrid (default): RRF over both branches. "
            "vector: dense embeddings only. "
            "bm25: lexical only. Switch to compare behavior on the same query."
        ),
    )
    top_k = st.slider(
        "Top-k chunks fed to the LLM", min_value=3, max_value=20, value=12,
        help="More chunks = broader recall but more context for the model to "
             "dilute. Default 12 because the corpus spans 2 docs (~6 chunks per doc).",
    )
    st.divider()
    st.markdown("**Sources in the index:**")
    for d in DOCS:
        st.caption(f"- {d.display} (FY ending {d.fiscal_year_ending})")
    st.caption("All answers grounded in these documents; no outside knowledge used.")


# === Main: question input + answer display ================================
st.markdown("## Ask Infosys's annual reports")
st.markdown(
    "Type a question below. The system retrieves relevant pages from the "
    "available reports (hybrid vector + BM25, fused via RRF), then gpt-4o-mini "
    "drafts an answer grounded **only** in those pages with per-document "
    "citations like `(FY24, p. 47)`. If the reports do not contain enough "
    "information, the system says so rather than guessing."
)

# Warm caches; surface the count so you know the index is alive.
stats = _warmup()
st.caption(f"Index ready: {stats['n_chunks']} chunks, BM25 over {stats['bm25_docs']} docs.")

# Pre-fill from sidebar click if any.
default_q = st.session_state.get("query_input", "")
query = st.text_input(
    "Your question",
    value=default_q,
    placeholder="e.g. What were Infosys's operating segments in FY24?",
    label_visibility="collapsed",
)

go = st.button("Ask", type="primary", disabled=not query.strip())

if go:
    with st.spinner("Retrieving and drafting..."):
        t0 = time.time()
        try:
            a = answer(query.strip(), top_k=top_k, mode=mode, doc_slugs=doc_slugs_filter)
        except Exception as e:
            st.error(f"Something went wrong: {type(e).__name__}: {e}")
            st.stop()
        elapsed = time.time() - t0

    # --- Answer block ----------------------------------------------------
    if a.abstained:
        # Distinct visual: yellow info box, no fake confidence.
        st.warning(
            "**The report does not contain enough information to answer this.**\n\n"
            f"{a.text.replace(ABSTAIN_SENTINEL, '').strip()}"
        )
    else:
        st.markdown("### Answer")
        st.markdown(a.text)

    # --- Telemetry strip ------------------------------------------------
    cols = st.columns(4)
    cols[0].metric("Latency", f"{elapsed:.2f} s")
    cols[1].metric("Mode", a.mode)
    cited_str = ", ".join(f"{c.doc_slug.upper()} p.{c.page}" for c in a.cited) or "—"
    cols[2].metric("Citations", cited_str)
    cols[3].metric("API cost", f"${a.cost_usd:.4f}")

    # --- Sanity report --------------------------------------------------
    # Surface deterministic post-hoc checks. The whole point of showing this
    # in the UI is to make the system's self-checking visible to reviewers:
    # silent guardrails do not communicate care.
    if a.sanity is not None:
        if a.sanity.has_failures:
            st.error("Sanity checks raised failures -- the answer is suspect.")
        elif a.sanity.has_warnings:
            st.info("Sanity checks passed with warnings.")
        with st.expander(f"Sanity checks ({len(a.sanity.checks)})", expanded=a.sanity.has_failures):
            for c in a.sanity.checks:
                icon = {"pass": "OK ", "warn": "WARN ", "fail": "FAIL "}.get(c.status, "")
                st.markdown(f"- **{icon}{c.name}** -- {c.detail}")

    # --- Sources: always shown, even on abstention (so you can see what we
    #     looked at and judge whether retrieval missed the right pages). ---
    cited_keys = {(c.doc_slug, c.page) for c in a.cited}
    with st.expander(f"Sources retrieved ({len(a.sources)} chunks)", expanded=False):
        for i, h in enumerate(a.sources, 1):
            badge_bits = []
            if h.rank_vector is not None:
                badge_bits.append(f"vec#{h.rank_vector} (cos {h.score_vector:.3f})")
            if h.rank_bm25 is not None:
                badge_bits.append(f"bm25#{h.rank_bm25} (score {h.score_bm25:.2f})")
            if h.rrf_score is not None:
                badge_bits.append(f"rrf={h.rrf_score:.4f}")
            cited_marker = (
                " — **CITED**"
                if (h.source_doc_slug, h.page_number) in cited_keys
                else ""
            )
            st.markdown(
                f"**{i}. {h.source_doc_display} · Page {h.page_number}**  ·  "
                f"*{', '.join(badge_bits)}*{cited_marker}"
            )
            preview = h.text.strip()
            if len(preview) > 600:
                preview = preview[:600] + "…"
            st.text(preview)
            st.divider()
