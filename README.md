# Infosys Annual Reports — Multi-Year Hybrid-Search RAG

**Live demo:** https://infosys-annual-report-rag-blptlnpfhpq2azdduxqpf8.streamlit.app/

A retrieval-augmented question-answering system over Infosys's **FY24 and
FY25 annual reports (Form 20-F)** — 296 + 359 pages, side-by-side, with
per-document citations. Built as a portfolio piece in ~18 hours over two
days (June 1–2, 2026). **Scope-honest**, not production-grade; limitations
are documented rather than hidden.

---

## TL;DR

- **Multi-doc, citation-grounded answers.** Ask a question, get a
  conversational answer with citations like `(FY24, p. 47)` or
  `(FY24, p. 47; FY25, p. 53)` for cross-year claims.
- **Hybrid retrieval**: dense embeddings (text-embedding-3-small, 1536-d)
  + lexical BM25, fused with Reciprocal Rank Fusion (k=60). Optional
  per-doc filter at query time via Chroma `where` clauses.
- **Abstention by default** when the corpus does not contain the answer
  (refuses to confabulate via a deterministic `INSUFFICIENT_CONTEXT:` sentinel).
- **Post-hoc sanity checks** on every answer (citation hygiene, valid
  doc slug, per-doc page-range, meta-comment detection) — visible in the UI.
- **Eval**: **11 / 14 PASS** on a hand-crafted 14-question set across
  6 categories. Both non-negotiable abstention questions PASS, and
  **both cross-year questions PASS with citations spanning both docs**
  (e.g. *"…employees grew from 317,240 to 323,578 (FY24, p. 37; FY25, p. 39)"*).
- **Cost**: ~$0.0007 per query at runtime (top-k=12, ~12K context tokens);
  one-time corpus ingest is ~$0.03 ($0.013 vision + $0.013 embed).
- **Stack**: PyMuPDF · OpenAI · ChromaDB · rank-bm25 · Streamlit. No
  LangChain, no LlamaIndex, no agent frameworks. Plain Python.

---

## Sources in the index

| Slug | Display | Fiscal year ending | Pages |
| --- | --- | --- | --- |
| `fy24` | Infosys FY24 | 2024-03-31 | 296 |
| `fy25` | Infosys FY25 | 2025-03-31 | 359 |

Adding a new annual report is a one-line change in [`src/docs.py`](src/docs.py)
plus a re-run of `python scripts/ingest.py`.

> **Honest note on the doc-year confusion:** the initial v1 of this repo
> was built and labeled around "FY24", but the PDF I started with was
> actually Infosys's **FY25** Form 20-F. The mistake was caught during
> the multi-doc upgrade when both PDFs were inspected programmatically.
> Everything is now correctly labeled, and the corpus genuinely spans
> both years. The git history (see `git log` from the multi-doc commit
> onward) shows the correction in full.

---

## Architecture

```
                +---------------------------+   +---------------------------+
                | data/infosys_ar_fy24.pdf  |   | data/infosys_ar_fy25.pdf  |
                |   (296 pages)             |   |   (359 pages)             |
                +-------------+-------------+   +-------------+-------------+
                              |                               |
                              v                               v
        +---------------------+-------------------------------+----------+
        |  src/parse.py   (Step 1)  -- runs per Doc in src/docs.py       |
        |  PyMuPDF text + tables -> Markdown                             |
        |  + deterministic image router  --(content_figure)-->  vision   |
        |    (decoration / portrait / content_figure)                    |
        +-------------+--------------------------------------------------+
                      |
                      v   data/parsed_fy24.json   +   data/parsed_fy25.json
        +-------------+--------------------------------------------------+
        |  src/chunk.py   (Step 2)                                       |
        |  one chunk per page + 50-token overlap (cl100k_base)           |
        |  chunk_id = "<slug>-p<NNN>"   carries source_doc_slug          |
        +-------------+--------------------------------------------------+
                      |
                      v   data/chunks.json  (combined across all docs)
        +-------------+--------------------------------------------------+
        |  src/embed.py   (Step 3)                                       |
        |  OpenAI text-embedding-3-small (1536-d)                        |
        |  -> chroma_db/  one collection "infosys_ar" w/ source metadata |
        +-------------+--------------------------------------------------+
                      |
                      v
   user query ----+--->  src/retrieve.py   (Step 4)
   (+ optional   |       vector_retrieve (Chroma, optional `where`)
    doc filter)  |       bm25_retrieve   (post-score doc filter)
                 |       hybrid_retrieve (RRF, k=60)
                 |
                 v
              src/answer.py   (Step 5)
              build context: "[FY24 · Page 47] ..."
              gpt-4o-mini @ T=0 with multi-doc grounding rules
              + INSUFFICIENT_CONTEXT: sentinel for abstention
              parse out (doc_slug, page) citations
                 |
                 v
              src/sanity.py   (Step 8)
              citations_present  /  citations_grounded
              citations_in_range (per-doc page max)  /  no_meta_comments
                 |
                 v
              app.py   (Step 6, Streamlit UI)
              -> answer + per-doc cites + sanity badges + sources panel
```

---

## Stack & design decisions

| Component        | Choice                                       | Why                                                                                               |
| ---------------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| PDF parsing      | **PyMuPDF (fitz)**                           | Fast, native table detection (`page.find_tables().to_markdown()`), no vision-extraction cost.    |
| Image handling   | **Deterministic router + selective vision**  | See "Vision routing" below.                                                                       |
| Chunking         | **Page-based, 50-token overlap**             | Pages map 1:1 to citations. Overlap preserves cross-page sentences; stays within doc boundary.    |
| Multi-doc plumbing | **Single Chroma collection + slug metadata** | One index keeps RRF simple; `where` clauses give per-doc filtering at query time. Add a doc -> one line in `src/docs.py`. |
| Embeddings       | **OpenAI text-embedding-3-small** (1536-d)   | Cheap (~$0.02/1M tok), high quality, no infra. Same model embeds chunks AND queries (symmetry).   |
| Vector store     | **ChromaDB, persistent mode**                | Cosine space; on-disk SQLite-backed; committed to repo so Cloud doesn't re-embed on boot.         |
| Lexical search   | **rank-bm25**                                | Pure Python, no infra. Fixes the dense-only blind spot for proper nouns, dollar amounts, etc.     |
| Hybrid fusion    | **Reciprocal Rank Fusion, k=60**             | Only needs ranks (not normalized scores) — avoids cosine-vs-BM25 calibration. k=60 from the paper.|
| Answer LLM       | **gpt-4o-mini @ T=0**                        | Cheap (~$0.0005 / answer). Deterministic at T=0 = reproducible answers per query.                 |
| Cite format      | **`(FY24, p. 47)` / `(FY24, p. 47; FY25, p. 53)`** | Doc + page in one cite; parser is a single regex; comparison answers naturally read multi-doc.   |
| Abstention       | **`INSUFFICIENT_CONTEXT:` sentinel**         | Forces a binary "answer or refuse" decision. Parseable downstream; eval-friendly.                 |
| Sanity layer     | **Deterministic post-hoc checks**            | Per-doc citation validation, page-range, meta-comment phrases. No extra LLM call.                |
| UI               | **Streamlit, single file (`app.py`)**        | Cheapest path to a public URL. Sidebar holds doc-filter / mode / top-k controls.                 |
| Deploy           | **Streamlit Community Cloud**                | Free public URL, GitHub-integrated CI. Python 3.11 pinned via `runtime.txt`.                     |

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

On the Infosys 20-Fs specifically, the router classified the vast majority
of image instances as decoration without API spend. The handful of vision
calls that did fire mostly landed on stock-photo dividers (correctly
tagged `PHOTO:` and filtered from downstream chunks). The **deliverable
here is the engineering judgment** — the router architecture is the demo,
not the (negligible) chart yield on these particular corporate PDFs.

### Per-doc filtering at retrieval (Step 4 deep-dive)

`hybrid_retrieve(query, doc_slugs=None)` accepts an optional doc-slug
filter:

- `doc_slugs=None` → search across all docs in the index (default for
  trend/comparison questions).
- `doc_slugs=["fy24"]` → translates to a Chroma `where` clause and a
  post-score BM25 filter — both branches restrict to that doc before RRF
  runs.

The UI sidebar exposes this as a "Limit retrieval to" radio. Useful for
defending answers: ask the same question with "All docs" and "FY24 only"
to see how grounded the response actually is in each year's report.

---

## Eval results

14 hand-crafted questions across 6 categories, run via
`python eval/run_eval.py`.

| Category        | Pass / Total | Notes                                                                 |
| --------------- | ------------ | --------------------------------------------------------------------- |
| fact_lookup     | 2 / 3        | One false fail (substring): model answered "Bengaluru" (current name); ground truth said "Bangalore". Semantic PASS. |
| trend           | 1 / 2        | One abstention on R&D-trend; arguable whether the corpus contains a true trend series for R&D-as-pct-of-revenue. |
| synthesis       | 2 / 3        | AI/Topaz and competitive risks pass with multi-page citations; ESG/net-zero abstained (retrieval missed "carbon" wording — see Limitations). |
| table_lookup    | 2 / 2        | Geographic revenue + operating segments — table extraction held up.   |
| **abstention**  | **2 / 2**    | **Non-negotiable.** Stock price + FY26 revenue — both correctly refused. |
| **cross_year**  | **2 / 2**    | Employee-count change cites `(FY24, p. 37; FY25, p. 39)`; AI/Topaz comparison cites both docs across 4 pages. |

**Total**: **11 / 14 auto-pass**, $0.010 total API cost, ~1.5 s/query average.

Full per-question results in [`eval/results.md`](eval/results.md);
audit-trail JSON in [`eval/results_raw.json`](eval/results_raw.json).

---

## Honest limitations

1. **Vector-drawn charts are invisible to retrieval.** PyMuPDF's
   `page.get_images()` only sees raster images. Charts authored in
   PowerPoint/Illustrator and embedded as PDF vector objects are NOT
   detected by the image router. Their data is only retrievable via any
   text labels that happen to live near them in the page text.

2. **Multimodal pipeline yields ~zero usable chart content on these docs.**
   We built the deterministic router + vision integration as designed,
   but the Infosys 20-Fs' raster images are overwhelmingly brand
   decoration + stock photography. The architecture demonstrates the
   pattern; the yield is incidental to this corpus.

3. **Long pages aren't subdivided.** Page-based chunking with mean ~1K
   tokens/chunk works well, but a small share of pages exceed 1500
   tokens. A single chunk that large dilutes retrieval precision. v2
   would split inside the page on paragraph boundaries while preserving
   page-as-cite.

4. **BM25 tokenizer is whitespace + lowercase, not stemmed.** Adequate
   for English financial prose; would miss morphological variants.
   Adding NLTK / Snowball stemming is a one-liner; skipped to keep the
   dependency footprint small.

5. **Sanity checks are deterministic, not semantic.** They catch
   ungrounded citations and meta-comment phrasing but cannot detect a
   *factually-wrong* answer that cites a real page. Semantic grading
   lives in the eval harness (and ultimately in the human reviewer).

6. **Corpus is two Infosys 20-Fs only.** Treat this as a demo of the
   pipeline, not a general-purpose RAG framework. Adding new docs (more
   years, or peer companies) is one config line in `src/docs.py` plus a
   re-ingest, but the prompt-level "this is about Infosys" framing
   would need to relax for cross-company use.

7. **No conversation memory / multi-turn.** Each query is independent.
   Follow-ups like "what about the segment breakdown for that?" would
   need a `(query, prior_context)` rewrite step.

8. **Auto-grader is coarse.** The eval auto-grade does
   substring-presence + abstention-correctness. Some "failures" are
   reasonably PASS on manual review (e.g. "Bengaluru" vs "Bangalore").
   The markdown report is the canonical scoring view.

9. **Doc-year mislabel in the v1 build.** I shipped the original
   single-doc version labeled "FY24" when the PDF was actually the FY25
   20-F. Caught only when the multi-doc work prompted me to inspect both
   PDFs' Form-20-F headers programmatically. Lesson: don't infer year
   from filename — always verify against the document content.

10. **chromadb 0.6 + opentelemetry deps fragility.** On Streamlit Cloud
    we hit a protobuf descriptor-API mismatch (chromadb pulls
    opentelemetry-proto generated with old protoc; Cloud installed
    protobuf >=5 which enforces stricter API checks). Fixed by pinning
    `protobuf>=4.21,<5` in `requirements.txt`. The pin is a temporary
    workaround tracking the chromadb/opentelemetry upgrade.

---

## v2 plans (in priority order)

1. **Section-aware chunking** to subdivide long pages on heading
   boundaries while preserving page-as-citation. Should noticeably
   improve precision on the ~5% of pages that exceed 1500 tokens.
2. **Vector-chart OCR**: render each page as image, use a lightweight
   chart-shape detector (axis-line counting on the rasterized page) to
   find vector-drawn charts the current router misses, then
   vision-extract.
3. **Async vision pipeline**: vision calls in Step 1 are sequential;
   with `asyncio.gather` + a semaphore, full ingest could drop
   meaningfully if a corpus had more content figures.
4. **Cross-encoder reranker** on the hybrid top-20 before passing top-8
   to the LLM. Should reduce the "retrieves close-but-not-quite"
   failure mode visible on some questions.
5. **Multi-turn**: query rewrite that uses prior turn context.
6. **More docs**: pull in FY22 + FY23 (deeper trend analysis) or a
   peer's 20-F (cross-company comparison). Both already supported by
   the pipeline; just need the PDFs and a one-line `src/docs.py` add.
7. **Tighten the auto-grader**: regex-with-OR for substring checks
   (e.g. `Bangalore|Bengaluru`), and a separate "this question doesn't
   have an answer in the corpus" ground-truth flag instead of
   conflating it with abstention expectations.

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

# Option B: rebuild everything from scratch (parse all docs -> chunk -> embed)
python scripts/ingest.py

# Run the eval set (14 questions across 6 categories)
python eval/run_eval.py

# Per-step CLIs (useful for incremental dev / smoke tests)
python -m src.parse --doc fy24           # parse one doc only
python -m src.retrieve --mode hybrid --doc fy24 "your query"   # filtered probe
python -m src.answer --doc fy24 "your query"                   # filtered answer
```

The Streamlit app boots at `http://localhost:8501`.

---

## Per-step build commit history

The commit log is meant to be read top-to-bottom as evidence-of-process:

```
Step 0  — project scaffold and dependencies
Step 1  — PyMuPDF parse + deterministic image router with vision routing
Step 2  — page-based chunking with 50-token overlap
Step 3  — OpenAI embeddings + persistent ChromaDB index + ingest pipeline
Step 4  — hybrid retrieval -- vector + BM25 + RRF
Step 5  — gpt-4o-mini answerer with citation grounding and abstention sentinel
Step 6  — Streamlit UI (app.py) for hybrid-RAG demo
Step 7  — eval set + harness (12 questions across 5 categories)
Step 8  — deterministic post-hoc sanity checks, wired into answer + UI
Step 9  — deploy hotfixes: Python 3.11 pin, protobuf<5 pin, runtime.txt
Step 10 — full README with live URL, architecture, eval, limitations
v1.1   — loosen narration to length-adaptive, lightly conversational
v1.2   — multi-doc (FY24 + FY25): docs config, per-doc cites, UI filter,
         sanity per-doc, expanded eval to 14 questions
```

Each commit message explains the design decision behind the step, not
just what changed. See `git log` for the full text.

---

## Cost summary

| Activity                                          | Cost      | Notes                                                                          |
| ------------------------------------------------- | --------- | ------------------------------------------------------------------------------ |
| Vision calls during parse (both docs)             | $0.013    | FY24: 0 raster images at all (fully vector-drawn); FY25: 2 vision calls.       |
| Embed full corpus (~662K tokens, 655 chunks)      | $0.013    | text-embedding-3-small, 7 batches of 100.                                      |
| Full eval run (14 questions)                      | $0.010    | gpt-4o-mini @ T=0, top-k=12.                                                   |
| Per-query at runtime (avg)                        | ~$0.0007  | ~12K context tokens to gpt-4o-mini.                                            |

**Total spent across the entire multi-doc build (parse + embed + eval + manual smoke tests)**: under $0.10.

---

## Acknowledgements

- Source documents: Infosys's annual reports (Form 20-F) — fiscal years
  ending March 31, 2024 and March 31, 2025. Publicly available via
  Infosys IR (https://www.infosys.com/investors/reports-filings/annual-report.html)
  and the SEC EDGAR system. Committed to this repo for full
  reproducibility; the documents are publicly distributed.
- RRF: Cormack, Clarke, Buettcher (2009), *Reciprocal Rank Fusion outperforms
  Condorcet and individual rank learning methods*.
