"""
Step 4: hybrid retrieval -- dense vector + sparse BM25 + Reciprocal Rank Fusion.

Three public functions:
  vector_retrieve(query, k)  -> top-k by cosine over Chroma embeddings
  bm25_retrieve(query, k)    -> top-k by BM25 over the same chunks
  hybrid_retrieve(query, k)  -> RRF over both branches

Why hybrid (not just vector)
----------------------------
Dense embeddings excel at *semantic* matches ("how did revenue grow?" matches
"YoY growth in operating income"). They struggle with rare proper nouns,
ticker symbols, monetary amounts, and acronyms ("INFY", "EUR 12.3 bn",
"DSO"), where exact lexical match is what you want. BM25 plugs that gap.

Reciprocal Rank Fusion
----------------------
RRF score for a doc = sum over each retriever R of:
    1 / (k + rank_R(doc))
where rank starts at 1 and k is a smoothing constant (60 is the value from
the original Cormack/Clarke/Buettcher 2009 paper). RRF only cares about
RANK, not raw scores, so we don't have to normalize cosine distances and
BM25 scores onto the same scale -- which is exactly the headache hybrid
schemes like CombSUM/weighted-sum impose.

Why k=60: it's the standard. Larger k flattens the contribution of top
ranks (less aggressive); smaller k makes the top of each list dominate.
We stick with the literature default rather than tuning it without an
eval set to tune against.

Loading model
-------------
- Chroma collection: opened once, cached via module-level handle.
- BM25 index: built once from chunks.json (cheap -- ~1s for 359 docs),
  cached via module-level handle.
- OpenAI client: instantiated once.
In Streamlit (app.py) the @st.cache_resource decorator wraps get_retriever()
so this whole bundle persists across reruns.
"""

from __future__ import annotations

# --- sqlite shim, must happen BEFORE 'import chromadb' on Streamlit Cloud ---
try:
    __import__("pysqlite3")
    import sys as _sys
    _sys.modules["sqlite3"] = _sys.modules["pysqlite3"]
except ImportError:
    pass
# ----------------------------------------------------------------------------

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import chromadb
from openai import OpenAI
from rank_bm25 import BM25Okapi

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHUNKS_PATH = PROJECT_ROOT / "data" / "chunks.json"
CHROMA_DIR = PROJECT_ROOT / "chroma_db"
COLLECTION_NAME = "infosys_ar"
EMBEDDING_MODEL = "text-embedding-3-small"

# RRF smoothing constant. 60 is the value from the original 2009 paper.
# Smaller -> top ranks dominate more; larger -> contributions flatten.
RRF_K = 60

# How many candidates to pull from each branch before fusing. We take more
# than the final k because RRF only ranks docs that appeared in at least
# one branch's top-N; raising N improves recall of the fused list.
PER_BRANCH_K = 20

# Simple BM25 tokenizer: lowercase, strip non-word chars, split on whitespace.
# Not stemmed (avoids an extra NLTK dep). Adequate for English financial prose;
# upgrade target if eval shows recall issues on morphological variants.
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class Hit:
    id: str
    page_number: int
    text: str
    rank_vector: int | None = None
    rank_bm25: int | None = None
    score_vector: float | None = None      # cosine distance: lower = better
    score_bm25: float | None = None        # BM25 raw score: higher = better
    rrf_score: float | None = None         # for hybrid; sum of 1/(k+rank) contributions
    rrf_components: dict = field(default_factory=dict)  # {'vector': 0.013, 'bm25': 0.016}


# === Lazy-loaded singletons ================================================
# Module-level caches; built on first use. Streamlit wraps these via
# @st.cache_resource at the UI layer so multiple sessions share one copy.

_chroma_collection = None
_bm25 = None
_bm25_chunks: list[dict] = []
_openai = None


def _get_chroma_collection():
    global _chroma_collection
    if _chroma_collection is None:
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _chroma_collection = client.get_collection(COLLECTION_NAME)
    return _chroma_collection


def _get_bm25():
    """Build BM25 index from chunks.json on first call. Caches the index
    and the source chunks list together so we can look up text + metadata
    by index after a BM25 score-sort."""
    global _bm25, _bm25_chunks
    if _bm25 is None:
        payload = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))
        _bm25_chunks = payload["chunks"]
        tokenized_corpus = [_tokenize(c["text"]) for c in _bm25_chunks]
        _bm25 = BM25Okapi(tokenized_corpus)
    return _bm25, _bm25_chunks


def _get_openai() -> OpenAI:
    global _openai
    if _openai is None:
        _openai = OpenAI()
    return _openai


# === Public API ============================================================

def vector_retrieve(query: str, k: int = 10) -> list[Hit]:
    """Embed query, query Chroma collection, return top-k by cosine."""
    oai = _get_openai()
    coll = _get_chroma_collection()

    qvec = oai.embeddings.create(model=EMBEDDING_MODEL, input=[query]).data[0].embedding
    res = coll.query(
        query_embeddings=[qvec],
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )

    hits: list[Hit] = []
    for rank, (cid, doc, meta, dist) in enumerate(zip(
        res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
    ), start=1):
        hits.append(Hit(
            id=cid,
            page_number=int(meta["page_number"]),
            text=doc,
            rank_vector=rank,
            score_vector=float(dist),
        ))
    return hits


def bm25_retrieve(query: str, k: int = 10) -> list[Hit]:
    """BM25 over the chunk corpus. Returns top-k by BM25 score."""
    bm25, chunks_list = _get_bm25()
    qtok = _tokenize(query)
    scores = bm25.get_scores(qtok)

    # argsort descending; take top-k. rank-bm25 returns numpy.float64 scores;
    # we cast to plain float for JSON-friendliness downstream.
    top_idx = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
    hits: list[Hit] = []
    for rank, idx in enumerate(top_idx, start=1):
        c = chunks_list[idx]
        hits.append(Hit(
            id=c["id"],
            page_number=int(c["page_number"]),
            text=c["text"],
            rank_bm25=rank,
            score_bm25=float(scores[idx]),
        ))
    return hits


def hybrid_retrieve(
    query: str,
    k: int = 10,
    per_branch_k: int = PER_BRANCH_K,
    rrf_k: int = RRF_K,
) -> list[Hit]:
    """RRF fusion of vector + BM25 branches.

    Pull top-`per_branch_k` from each branch (default 20), compute RRF for
    each unique doc, return top-`k` overall.
    """
    vec_hits = vector_retrieve(query, k=per_branch_k)
    bm25_hits = bm25_retrieve(query, k=per_branch_k)

    # Merge by id. For each doc seen in either branch, accumulate RRF
    # contributions and remember whichever scores/ranks we have.
    merged: dict[str, Hit] = {}

    def _upsert(hit: Hit, branch: str, rank: int) -> None:
        h = merged.get(hit.id)
        if h is None:
            h = Hit(id=hit.id, page_number=hit.page_number, text=hit.text)
            merged[hit.id] = h
        contribution = 1.0 / (rrf_k + rank)
        h.rrf_score = (h.rrf_score or 0.0) + contribution
        h.rrf_components[branch] = contribution
        if branch == "vector":
            h.rank_vector = hit.rank_vector
            h.score_vector = hit.score_vector
        else:
            h.rank_bm25 = hit.rank_bm25
            h.score_bm25 = hit.score_bm25

    for h in vec_hits:
        _upsert(h, "vector", h.rank_vector)
    for h in bm25_hits:
        _upsert(h, "bm25", h.rank_bm25)

    fused = sorted(merged.values(), key=lambda h: -(h.rrf_score or 0.0))
    return fused[:k]


# === CLI for quick manual probing =========================================
# Lets us spot-check retrieval quality without spinning up Streamlit:
#   python -m src.retrieve "What was revenue in FY24"

def _cli() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Quick retrieval probe.")
    parser.add_argument("query", nargs="+", help="Free-form question.")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--mode", choices=("hybrid", "vector", "bm25"), default="hybrid")
    args = parser.parse_args()
    q = " ".join(args.query)

    fn = {"hybrid": hybrid_retrieve, "vector": vector_retrieve, "bm25": bm25_retrieve}[args.mode]
    hits = fn(q, k=args.k)
    print(f"query : {q!r}")
    print(f"mode  : {args.mode}, top-{args.k}")
    print("-" * 70)
    for i, h in enumerate(hits, 1):
        details = []
        if h.rank_vector is not None:
            details.append(f"vec#{h.rank_vector}/{h.score_vector:.3f}")
        if h.rank_bm25 is not None:
            details.append(f"bm25#{h.rank_bm25}/{h.score_bm25:.2f}")
        if h.rrf_score is not None:
            details.append(f"rrf={h.rrf_score:.4f}")
        print(f"{i}. p.{h.page_number:3d} {h.id}  [{', '.join(details)}]")
        print(f"   {h.text[:180].strip()}...")


if __name__ == "__main__":
    _cli()
