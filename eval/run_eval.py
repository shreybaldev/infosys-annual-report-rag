"""
Run the eval question set through the RAG, auto-grade where possible, and
emit two artifacts:

  eval/results_raw.json -- full per-question payload (question, answer text,
                           cited pages, sources, usage, cost, auto-grade).
                           Reproducible record; check into the repo.
  eval/results.md       -- human-readable summary, scored. Edit by hand to
                           add qualitative judgment beyond the auto-grade.

Auto-grading is deliberately coarse:
  - abstention correctness    -> exact (we know whether it abstained)
  - factual substring match   -> case-insensitive substring of expected_answer_substring
                                 in the answer text
A "pass" needs BOTH the right abstention behavior AND the substring presence
(when applicable). Real qualitative grading goes in results.md.

Why two files: the JSON is the audit trail (rerun-friendly, diffable);
the markdown is the cover story for the README / interviewer.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.answer import answer  # noqa: E402

QUESTIONS_PATH = PROJECT_ROOT / "eval" / "questions.json"
RAW_OUT_PATH = PROJECT_ROOT / "eval" / "results_raw.json"
MD_OUT_PATH = PROJECT_ROOT / "eval" / "results.md"


def _grade(q: dict, a) -> tuple[bool, str]:
    """Returns (passed, reason)."""
    expects_abstain = q.get("expected_abstain", False)
    expected_sub = (q.get("expected_answer_substring") or "").strip()

    if expects_abstain:
        if a.abstained:
            return True, "abstained as expected"
        return False, "did NOT abstain (model produced an answer instead)"
    # expects a real answer
    if a.abstained:
        return False, "abstained when an answer was expected"
    if expected_sub and expected_sub.lower() not in a.text.lower():
        return False, f"answer missing expected substring '{expected_sub}'"
    return True, "substring matched" if expected_sub else "answered (no substring check defined)"


def main() -> None:
    qs = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    print(f"[eval] running {len(qs['questions'])} questions...")

    results = []
    total_cost = 0.0
    total_latency = 0.0
    n_pass = 0

    for i, q in enumerate(qs["questions"], 1):
        t0 = time.time()
        a = answer(q["question"])
        dt = time.time() - t0
        passed, reason = _grade(q, a)
        n_pass += int(passed)
        total_cost += a.cost_usd
        total_latency += dt

        print(
            f"[eval] {i:2d}/{len(qs['questions'])} [{q['category']:13s}] "
            f"{'PASS' if passed else 'FAIL'}  ({reason})  "
            f"cited={a.cited_pages}  abstain={a.abstained}  ${a.cost_usd:.4f}"
        )

        results.append({
            "id": q["id"],
            "category": q["category"],
            "question": q["question"],
            "expected_abstain": q.get("expected_abstain", False),
            "expected_substring": q.get("expected_answer_substring", ""),
            "answer_text": a.text,
            "cited_pages": a.cited_pages,
            "abstained": a.abstained,
            "source_pages": [h.page_number for h in a.sources],
            "latency_s": round(dt, 2),
            "cost_usd": a.cost_usd,
            "usage": a.usage,
            "auto_grade": {"passed": passed, "reason": reason},
            "notes_truth": q.get("notes", ""),
        })

    # --- write raw json ----------------------------------------------------
    summary = {
        "ran_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_questions": len(results),
        "n_passed_auto": n_pass,
        "total_cost_usd": round(total_cost, 4),
        "total_latency_s": round(total_latency, 1),
        "avg_latency_s": round(total_latency / len(results), 2),
        "results": results,
    }
    RAW_OUT_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[eval] wrote {RAW_OUT_PATH}")

    # --- write markdown ----------------------------------------------------
    md = _render_md(qs["meta"], summary)
    MD_OUT_PATH.write_text(md, encoding="utf-8")
    print(f"[eval] wrote {MD_OUT_PATH}")
    print(f"[eval] auto-grade: {n_pass}/{len(results)} passed, ${total_cost:.4f} total")


def _render_md(meta: dict, summary: dict) -> str:
    """Produce eval/results.md -- a human-readable scoring view."""
    lines: list[str] = []
    lines.append("# Eval results -- Infosys FY24 RAG")
    lines.append("")
    lines.append(f"**Ran at (UTC):** {summary['ran_at_utc']}  ")
    lines.append(f"**Model:** {meta['model']}  ")
    lines.append(f"**Retrieval:** {meta['retrieval']}  ")
    lines.append(f"**Source doc:** {meta['source_doc']}  ")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Auto-pass: **{summary['n_passed_auto']} / {summary['n_questions']}**")
    lines.append(f"- Total API cost: **${summary['total_cost_usd']}**")
    lines.append(f"- Avg latency: **{summary['avg_latency_s']} s/query**")
    lines.append("")
    lines.append("Auto-grade is coarse (abstention correctness + expected-substring presence).")
    lines.append("The per-question table below is the canonical scoring view -- edit the")
    lines.append("**Manual** column after reading each answer.")
    lines.append("")
    lines.append("## Per-question results")
    lines.append("")

    for r in summary["results"]:
        verdict = "PASS" if r["auto_grade"]["passed"] else "FAIL"
        lines.append(f"### `{r['id']}` ({r['category']}) -- auto: {verdict}")
        lines.append("")
        lines.append(f"**Q:** {r['question']}")
        lines.append("")
        if r["expected_abstain"]:
            lines.append("**Expected:** abstention (no answer in the doc)")
        else:
            sub = r["expected_substring"] or "(no substring check)"
            lines.append(f"**Expected:** real answer containing `{sub}`")
        lines.append("")
        lines.append(f"**Answer:**\n\n> {r['answer_text'].replace(chr(10), chr(10) + '> ')}")
        lines.append("")
        lines.append(
            f"- abstained: `{r['abstained']}`  "
            f"- cited pages: `{r['cited_pages']}`  "
            f"- sources retrieved: `{r['source_pages']}`  "
            f"- latency: {r['latency_s']}s  "
            f"- cost: ${r['cost_usd']}"
        )
        lines.append(f"- auto-grade reason: {r['auto_grade']['reason']}")
        lines.append("- **Manual:** _(edit me: pass / fail / partial; one sentence on what was right or off)_")
        lines.append("")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
