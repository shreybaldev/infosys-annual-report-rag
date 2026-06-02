# Infosys FY24 Annual Report — Hybrid-Search RAG

**Live demo:** https://infosys-annual-report-rag-blptlnpfhpq2azdduxqpf8.streamlit.app/

A retrieval-augmented question-answering system over Infosys's 359-page
FY24 annual report. Built as a portfolio piece in ~15 hours over two days
(June 1–2, 2026) — the build is **scope-honest**, not production-grade, and
limitations are documented rather than hidden.

---

## TL;DR

- **Single PDF in, citation-grounded answer out.** Ask a question, get a 2–5
  sentence answer with `(p. 47)`-style page citations.
- **Hybrid retrieval**: dense embeddings (text-embedding-3-small) +
  lexical BM25, fused with Reciprocal Rank Fusion (k=60).
- **Abstention by default** when the report does not contain the answer
  (refuses to confabulate via a deterministic `INSUFFICIENT_CONTEXT:` sentinel).
- **Post-hoc sanity checks** on every answer (citation hygiene, page-range,
  meta-comment detection) — visible to the user in the UI.
- **Eval**: 10 / 12 PASS on a hand-crafted 12-question set across five
  categories. Both non-negotiable abstention questions PASS.
- **Cost**: ~$0.0005 per query at runtime, $0.02 for full corpus ingest.
- **Stack**: PyMuPDF · OpenAI · ChromaDB · rank-bm25 · Streamlit. No
  LangChain, no LlamaIndex, no agent frameworks. Plain Python.

---

## Architecture

```
                    +----------------------+
                    |  data/infosys_ar.pdf |
                    |     (359 pages)      |
                    +----------+-----------+
                               |
                               v
       +-----------------------+-----------------------+
       |   src/parse.py        (Step 1)                |
       |  PyMuPDF text + tables-as-markdown            |
       |  + deterministic image router  ---> vision    |
       |    (decoration/portrait/content_figure)       |
       +-----------------------+-----------------------+
                               |
                               v   data/parsed.json
       +-----------------------+-----------------------+
       |   src/chunk.py        (Step 2)                |
       |  one chunk per page + 50-token overlap        |
       |  (cl100k_base tokenizer)                      |
       +-----------------------+-----------------------+
                               |
                               v   data/chunks.json
       +-----------------------+-----------------------+
       |   src/embed.py        (Step 3)                |
       |  OpenAI text-embedding-3-small (1536-dim)     |
       |  -> chroma_db/  collection "infosys_ar"       |
       +-----------------------+-----------------------+
                               |
                               v
   user query -> +-------------+-------------+
                 | src/retrieve.py  (Step 4) |
                 |  vector_retrieve  (Chroma)|
                 |  bm25_retrieve    (BM25)  |
                 |  hybrid_retrieve  (RRF60) |
                 +-------------+-------------+
                               |
                               v   top-k Hit list
                 +-------------+-------------+
                 | src/answer.py    (Step 5) |
                 |  build context block      |
                 |  gpt-4o-mini @ T=0        |
                 |  + grounding rules        |
                 |  + INSUFFICIENT_CONTEXT   |
                 |    abstention sentinel    |
                 +-------------+-------------+
                               |
                               v   Answer (text, cites, sources)
                 +-------------+-------------+
                 | src/sanity.py    (Step 8) |
                 |  citations_present        |
                 |  citations_grounded       |
                 |  citations_in_range       |
                 |  no_meta_comments         |
                 +-------------+-------------+
                               |
                               v
                 +-------------+-------------+
                 |   app.py         (Step 6) |
                 |   Streamlit UI            |
                 +---------------------------+
```

---

## Stack & design decisions

| Component        | Choice                                       | Why                                                                                               |
| ---------------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| PDF parsing      | **PyMuPDF (fitz)**                           | Fast, native table detection (`page.find_tables().to_markdown()`), no vision-extraction cost.    |
| Image handling   | **Deterministic router + selective vision**  | See "Vision routing" below.                                                                       |
| Chunking         | **Page-based, 50-token overlap**             | Pages map 1:1 to citations. Overlap preserves sentence-spanning context across page breaks.       |
| Embeddings       | **OpenAI text-embedding-3-small** (1536d)    | Cheap (~$0.02/1M tok), high quality, no infra. $0.007 to embed the whole corpus.                  |
| Vector store     | **ChromaDB, persistent mode**                | Cosine space; on-disk SQLite-backed; committed to repo so Cloud doesn't re-embed on boot.         |
| Lexical search   | **rank-bm25**                                | Pure Python, no infra. Fixes the dense-only blind spot for proper nouns, dollar amounts, etc.     |
| Hybrid fusion    | **Reciprocal Rank Fusion, k=60**             | Only needs ranks (not normalized scores) — avoids cosine-vs-BM25 calibration. k=60 from the paper.|
| Answer LLM       | **gpt-4o-mini @ T=0**                        | Cheap (~$0.0005 / answer). Deterministic at T=0 = reproducible answers per query.                 |
| Abstention       | **`INSUFFICIENT_CONTEXT:` sentinel**         | Forces a binary "answer or refuse" decision. Parseable downstream; eval-friendly.                 |
| Sanity layer     | **Deterministic post-hoc checks**            | Citations validated against retrieved sources, page-range, meta-comment phrases. No extra LLM call.|
| UI               | **Streamlit, single file (`app.py`)**        | Cheapest path to a public URL. No separate FastAPI / React layer.                                 |
| Deploy           | **Streamlit Community Cloud**                | Free public URL, GitHub-integrated CI.                                                            |

### Vision routing (Step 1 deep-dive)

Annual reports have charts that text extraction misses. But naively
vision-calling every detected image wastes API budget on logos, portraits,
and brand decorations. The router classifies each detected image with
**zero API cost** before deciding whether to spend vision dollars:

```
brand-repeated xref   -> decoration   (same image on >10 pages = brand strip)
short side < 200 px   -> decoration   (logos, bullets, icons)
aspect > 6.0          -> decoration   (banners, dividers)
covers >=40% page,
  anchored at corner  -> decoration   (full-page background photos)
has caption nearby    -> content_figure  (CAPTIONED -> vision call)
mid-page inset,
  large enough        -> content_figure  (NON-CORNER -> vision call)
square-ish + mid-size -> portrait     (skip, but kept in metadata)
fallthrough           -> decoration   (conservative)
```

For the Infosys FY24 PDF specifically, this classified **467 of 469 image
instances as decoration without API spend**. The 2 calls that fired both
landed on stock-photo dividers (correctly tagged `PHOTO:` and filtered from
downstream chunks). The **deliverable here is the engineering judgment** —
the router architecture is the demo, not the (negligible) chart yield on
this particular document.

---

## Eval results

12 hand-crafted questions across 5 categories, run via `python eval/run_eval.py`.

| Category        | Pass / Total | Notes                                                                 |
| --------------- | ------------ | --------------------------------------------------------------------- |
| fact_lookup     | 2 / 3        | One false fail: model answered "Bengaluru" (current name); ground-truth substring said "Bangalore". Semantic PASS. |
| trend           | 1 / 2        | One arguable: model abstained on an R&D-trend question; the report may not contain that series, in which case abstention is correct behavior. |
| synthesis       | 3 / 3        | AI/Topaz strategy, competitive risks, ESG/sustainability — all answered with multi-page citations. |
| table_lookup    | 2 / 2        | Geographic revenue + operating segments — table extraction held up.   |
| **abstention**  | **2 / 2**    | **Non-negotiable.** Stock price + FY26 revenue — both correctly refused. |

**Total**: 10 / 12 auto-pass, $0.006 total API cost, ~1.2 s/query average.

Full per-question results in [`eval/results.md`](eval/results.md);
audit-trail JSON in [`eval/results_raw.json`](eval/results_raw.json).

---

## Honest limitations

This is a v1 portfolio piece. The following gaps are real:

1. **Vector-drawn charts are invisible to retrieval.** PyMuPDF's
   `page.get_images()` only sees raster images. Charts authored in
   PowerPoint/Illustrator and embedded as PDF vector objects (most of the
   report body, pp. 1–294) are NOT detected by the image router. Their
   data is only retrievable via any text labels that happen to live near
   them.

2. **Multimodal pipeline yielded ~zero usable chart content on this doc.**
   We built the deterministic router + vision integration as designed, but
   the Infosys FY24 PDF's raster images are overwhelmingly brand decoration
   + stock photography (see "Vision routing" above). The architecture
   demonstrates the pattern; the yield is incidental to this corpus.

3. **Long pages aren't subdivided.** Page-based chunking with mean 974
   tokens / chunk works well, but ~5% of pages exceed 1500 tokens. A
   single chunk that large dilutes retrieval precision. v2 would split
   inside the page on paragraph boundaries while preserving page-as-cite.

4. **BM25 tokenizer is whitespace + lowercase, not stemmed.** Adequate
   for English financial prose; would miss morphological variants
   ("growing" vs "grew"). Adding NLTK / Snowball stemming is a one-liner;
   skipped to keep the dependency footprint small.

5. **Sanity checks are deterministic, not semantic.** They catch
   ungrounded citations and meta-comment phrasing but cannot detect a
   *factually-wrong* answer that cites a real page. Semantic grading lives
   in the eval harness (and ultimately in the human reviewer).

6. **Single-corpus.** This system is hard-coded to one document; treat
   it as a demo of the pipeline, not a general-purpose RAG framework.

7. **No conversation memory / multi-turn.** Each query is independent.
   Follow-ups like "what about the segment breakdown for that?" would
   need a `(query, prior_context)` rewrite step.

8. **Auto-grader is coarse.** The eval auto-grade does
   substring-presence + abstention-correctness. Two of our "failures"
   are reasonably PASS on manual review (see Eval Results above). The
   markdown report is the canonical scoring view.

9. **chromadb 0.6 + opentelemetry deps fragility.** On Streamlit Cloud
   we hit a protobuf descriptor-API mismatch (chromadb pulls
   opentelemetry-proto generated with old protoc; Cloud installed
   protobuf >=5 which enforces stricter API checks). Fixed by pinning
   `protobuf>=4.21,<5` in `requirements.txt`. The pin is a temporary
   workaround tracking the chromadb/opentelemetry upgrade.

---

## v2 plans (in priority order)

1. **Section-aware chunking** to subdivide long pages on heading boundaries
   while preserving page-as-citation. Should noticeably improve precision
   on the ~5% of pages that exceed 1500 tokens.
2. **Vector-chart OCR**: render each page as image, use a lightweight
   chart-shape detector (axis-line counting on the rasterized page) to
   find vector-drawn charts the current router misses, then vision-extract.
3. **Async vision pipeline**: vision calls in Step 1 are sequential; with
   `asyncio.gather` + a semaphore, full ingest could drop from ~5 min to
   ~30 s if there were more content figures to process.
4. **Cross-encoder reranker** on the hybrid top-20 before passing top-8
   to the LLM. Should reduce the "retrieves close-but-not-quite" failure
   mode visible on the revenue question.
5. **Multi-turn**: query rewrite that uses prior turn context.
6. **Tighten the auto-grader**: regex-with-OR for substring checks
   (e.g. `Bangalore|Bengaluru`), and a separate "this question doesn't
   have an answer in the doc" ground-truth flag instead of conflating it
   with abstention expectations.

---

## Running locally

```powershell
# Windows / PowerShell. Python 3.11.

git clone https://github.com/shreybaldev/infosys-annual-report-rag
cd infosys-annual-report-rag

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Set your key (persisted for your Windows user)
[System.Environment]::SetEnvironmentVariable('OPENAI_API_KEY', 'sk-...', 'User')
# ...and for the current session
$env:OPENAI_API_KEY = 'sk-...'

# Option A: just run the UI (uses the committed chroma_db/)
streamlit run app.py

# Option B: rebuild everything from scratch (parse -> chunk -> embed)
python scripts/ingest.py

# Run the eval set
python eval/run_eval.py
```

The Streamlit app boots at `http://localhost:8501`.

---

## Per-step build commit history

The commit log is meant to be read top-to-bottom as evidence-of-process:

```
Step 0 — project scaffold and dependencies
Step 1 — PyMuPDF parse + deterministic image router with vision routing
Step 2 — page-based chunking with 50-token overlap
Step 3 — OpenAI embeddings + persistent ChromaDB index + ingest pipeline
Step 4 — hybrid retrieval -- vector + BM25 + RRF
Step 5 — gpt-4o-mini answerer with citation grounding and abstention sentinel
Step 6 — Streamlit UI (app.py) for hybrid-RAG demo
Step 7 — eval set + harness (12 questions across 5 categories)
Step 8 — deterministic post-hoc sanity checks, wired into answer + UI
Step 9 — deploy hotfixes: Python 3.11 pin, protobuf<5 pin, runtime.txt
```

Each commit message explains the design decision behind the step, not just
what changed. See `git log` for the full text.

---

## Cost summary

| Activity                              | One-time cost | Notes                              |
| ------------------------------------- | ------------- | ---------------------------------- |
| Vision calls during parse (2 calls)   | $0.013        | Both landed on stock photos.       |
| Embed full corpus (350K tokens)       | $0.007        | text-embedding-3-small.            |
| Full eval run (12 questions)          | $0.006        | gpt-4o-mini @ T=0.                 |
| Per-query at runtime (avg)            | ~$0.0005      | ~3K context tokens to gpt-4o-mini. |

**Total spent during build**: under $0.05.

---

## Acknowledgements

- Source document: [Infosys FY24 Annual Report (Form 20-F)](https://www.infosys.com/investors/reports-filings/annual-report.html).
  Committed to this repo (`data/infosys_ar.pdf`) for full reproducibility;
  the report is publicly distributed.
- RRF: Cormack, Clarke, Buettcher (2009), *Reciprocal Rank Fusion outperforms
  Condorcet and individual rank learning methods*.
