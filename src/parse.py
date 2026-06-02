"""
Step 1: PDF -> structured per-page data, with a deterministic router that
sends only the *interesting* images through a vision model.

For each page we extract:
  - Plain text (PyMuPDF's text extraction, single-column reading order).
  - Tables, rendered as GitHub-flavored Markdown. Markdown preserves columnar
    structure for the LLM at retrieval time, where plain-text extraction
    would flatten alignment to whitespace.
  - Images, classified deterministically before any API call:
        decoration     -> skipped (logos, brand strips, dividers, repeated headers)
        portrait       -> placeholder kept in metadata but not vision-described
        content_figure -> sent to gpt-4o-mini vision for a 2-5 sentence description

Why the router exists
---------------------
A 360-page annual report has ~50-80 substantive charts/graphs but ~200+
decorative or repeated images (page-header brand strips, bullet icons,
chairman portraits). Naively vision-calling every image wastes ~10x the
budget and pollutes downstream chunks with junk descriptions ("DECORATION",
"PHOTO: a man in a suit"). A deterministic classifier (size + aspect ratio
+ xref repetition + caption-text proximity) gets us most of the way there
for $0 before any API call.

Limitations (documented for the README, not hidden)
---------------------------------------------------
- Vector-drawn charts (charts authored in Illustrator/PowerPoint and embedded
  as PDF vector objects rather than raster images) are NOT seen by
  page.get_images(). We catch raster-embedded charts only. Many annual
  reports do export charts as PNGs, so this covers a meaningful slice, but
  not all of it.
- Caption proximity is heuristic (text within 100px below the image). A
  caption on the LEFT or ABOVE the image will be missed.
- The vision model can hallucinate numeric values from low-resolution charts.
  We render at 144 DPI ("high" detail) to mitigate, but a v2 cross-check
  against same-page tables would be safer.

Output: data/parsed.json (deterministic, committed to repo).
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import fitz  # PyMuPDF
from openai import OpenAI

# === Paths =================================================================
# Source-of-truth for the corpus lives in src/docs.py. parse.py consumes
# a Doc and writes a per-doc parsed file. main() iterates DOCS by default
# but accepts --doc <slug> to re-parse just one.
from src.docs import DOCS, DOCS_BY_SLUG, Doc, PROJECT_ROOT, parsed_json_path

# === Router thresholds =====================================================
# Tuning bias: prefer FALSE NEGATIVES over false positives. A missed chart
# costs us one retrieval miss (and goes in the README's Known Limitations).
# A false positive costs an API call + pollutes the downstream chunk with a
# "DECORATION"/"PHOTO" string we then have to strip.
MIN_CONTENT_DIM_PX = 200          # below this on either dim -> logo / bullet / icon
MAX_DECORATION_ASPECT = 6.0       # very thin -> banner / divider
BRAND_REPETITION_THRESHOLD = 10   # same xref reused on >N pages -> brand strip / header
CAPTION_LOOKAHEAD_PX = 100        # search this far BELOW an image bbox for captions
PORTRAIT_MAX_DIM_PX = 600         # square-ish + below this -> probably a person, not a chart

# Section-divider / stock-photo detection: corporate reports use full-page or
# half-page lifestyle photography as chapter openers. These start at page
# corner (0,0) or (page_w/2, 0) and cover a large fraction of the page area.
# Charts are almost always inset within content margins instead.
# Empirically tuned from the smoke-test misclassifications.
PAGE_CORNER_TOLERANCE_PX = 20     # bbox top-left within this distance of page corner
PAGE_COVERAGE_DECORATION_FRAC = 0.40  # bbox covers >= this fraction of page area

# Captions in annual reports almost always start with one of these tokens.
# Including 'source' and 'note' catches data attribution lines that sit
# directly beneath charts.
CAPTION_PATTERNS = re.compile(
    r"\b(figure|fig\.?|chart|graph|exhibit|table|source|note)\b\s*[:.\d]",
    re.IGNORECASE,
)

# === Vision config =========================================================
# gpt-4o-mini is the cheapest OpenAI multimodal model. "high" detail tiles
# the image into 512x512 chunks at 170 tokens each; for our ~1000px-on-the-
# long-side renders that's ~500-800 input tokens. With ~80 calls at ~$0.0003
# each, full ingest cost is <$0.05. Worth it vs. "low" (85 tokens, 512x512
# downsample) which would render small chart labels illegible.
VISION_MODEL = "gpt-4o-mini"
VISION_DETAIL = "high"
VISION_RENDER_DPI = 144            # 2x the PDF default of 72 -> enough for chart labels
VISION_MAX_OUTPUT_TOKENS = 400     # ~3-5 sentences

# Public OpenAI pricing for gpt-4o-mini (per 1M tokens). Used for the running
# cost estimate printed during parse. Update if pricing changes.
COST_PER_1M_INPUT_USD = 0.15
COST_PER_1M_OUTPUT_USD = 0.60

# The vision prompt is intentionally narrow: we want descriptions DENSE with
# retrieval-useful tokens (numbers, axis labels, segment names) and terse
# fallback strings for non-content cases so they don't pollute the chunks
# that go to embedding.
VISION_PROMPT = (
    "You are extracting information from an image embedded in Infosys's FY24 "
    "annual report.\n\n"
    "If it is a chart, graph, infographic, dashboard, or table: describe it in "
    "2-5 sentences INCLUDING all numeric values, axis labels, segment names, "
    "units, time periods, and any obvious takeaway. Be precise; if a label is "
    "unreadable, say 'unreadable'.\n\n"
    "If it is a photograph of a person: respond exactly with the line: "
    "PHOTO: portrait of {name or role if visible}.\n\n"
    "If it is purely decorative (logo, divider, brand strip, abstract pattern): "
    "respond with exactly the single word: DECORATION.\n\n"
    "Do not speculate beyond what the image shows."
)

ImageClass = Literal["decoration", "portrait", "content_figure"]


# === Per-page extraction helpers ===========================================

def _extract_text(page: "fitz.Page") -> str:
    """PyMuPDF's default text extractor preserves reading order well for
    single-column reports. We don't use 'blocks' mode because column-aware
    handling isn't needed here."""
    return page.get_text("text").strip()


def _extract_tables_md(page: "fitz.Page") -> list[str]:
    """find_tables() returns a TableFinder; each Table has .to_markdown().
    False positives (text that's just visually aligned) are an accepted v1
    cost -- they render as messy markdown but don't break downstream."""
    tables: list[str] = []
    try:
        finder = page.find_tables()
        for tbl in finder.tables:
            md = tbl.to_markdown().strip()
            if md:
                tables.append(md)
    except Exception:
        # find_tables() can throw on unusual page layouts. Silent skip is
        # preferable to crashing the whole parse on one weird page.
        pass
    return tables


def _find_nearby_caption(bbox: "fitz.Rect", page: "fitz.Page") -> str | None:
    """Grab any text block whose top edge is within CAPTION_LOOKAHEAD_PX of
    the image's bottom edge AND starts with a caption marker. Returns None
    if no caption-like text is found nearby (most images won't have one)."""
    band = fitz.Rect(bbox.x0, bbox.y1, bbox.x1, bbox.y1 + CAPTION_LOOKAHEAD_PX)
    text = page.get_textbox(band).strip()
    if not text:
        return None
    # Only count it as a caption if the first ~200 chars look captionish --
    # otherwise it's just body copy that happens to sit near the image.
    if CAPTION_PATTERNS.search(text[:200]):
        return text[:200]
    return None


def _classify_image(
    bbox: "fitz.Rect",
    page_width: float,
    page_height: float,
    xref_repetition_count: int,
    caption_hint: str | None,
) -> tuple[ImageClass, str]:
    """Pure-function deterministic router. Order matters: cheap rejections
    first, then positive content signals, then conservative defaults.

    Returns (classification, human-readable reason). The reason gets stored
    in parsed.json so we can audit the router's choices after the fact.

    Tuning bias (revised after smoke-test on pages 295-310):
      - The smoke test surfaced full-page stock-photo dividers
        ('large + uncaptioned + corner-anchored') being misclassified as
        content. We now treat 'starts at page corner AND covers a large
        fraction of page area' as a strong decoration signal.
      - We also removed the over-generous 'large + uncaptioned -> content'
        default; without a caption, we now lean conservative. This trades
        some recall on uncaptioned charts (added to README limitations) for
        a meaningful drop in vision-API waste on lifestyle photography.
    """
    width = bbox.width
    height = bbox.height
    long_side = max(width, height)
    short_side = min(width, height)
    aspect = (long_side / short_side) if short_side > 0 else 999.0
    page_area = page_width * page_height
    img_area = width * height
    coverage = img_area / page_area if page_area > 0 else 0.0
    starts_at_corner = (bbox.x0 < PAGE_CORNER_TOLERANCE_PX
                        and bbox.y0 < PAGE_CORNER_TOLERANCE_PX)
    starts_at_midpage_top = (
        abs(bbox.x0 - page_width / 2) < PAGE_CORNER_TOLERANCE_PX
        and bbox.y0 < PAGE_CORNER_TOLERANCE_PX
    )

    # 1) Brand element reused across many pages (page-header strip, footer logo).
    if xref_repetition_count > BRAND_REPETITION_THRESHOLD:
        return ("decoration", f"image xref reused on {xref_repetition_count} pages (brand element)")

    # 2) Too small on the short side -> icon, bullet, tiny logo.
    if short_side < MIN_CONTENT_DIM_PX:
        return ("decoration", f"too small ({int(width)}x{int(height)} px)")

    # 3) Very thin -> banner / divider.
    if aspect > MAX_DECORATION_ASPECT:
        return ("decoration", f"aspect ratio {aspect:.1f}:1 (banner/divider)")

    # 4) Page-spanning, corner-anchored -> section-divider stock photo / brand background.
    # This rule was added after smoke-testing showed 8/8 misclassifications
    # came from this exact pattern (full-page or half-page lifestyle photos
    # anchored at the page corner).
    if (starts_at_corner or starts_at_midpage_top) and coverage >= PAGE_COVERAGE_DECORATION_FRAC:
        return ("decoration", f"corner-anchored, covers {coverage*100:.0f}% of page (background photo)")

    # 5) Positive caption signal -> almost certainly content. Strongest signal we have.
    if caption_hint:
        snippet = caption_hint[:50].replace("\n", " ")
        return ("content_figure", f"caption nearby ('{snippet}...')")

    # 6) Mid-page inset (not anchored at page corner) AND large -> likely a real
    # data figure. Stock-photo dividers and brand panels overwhelmingly anchor
    # to a page corner; charts/infographics get inset within content margins.
    # We tolerate the false-positive cost (one wasted vision call here and
    # there) to recover real charts the strict router would otherwise miss.
    if (not starts_at_corner and not starts_at_midpage_top
            and long_side >= 300 and short_side >= 200):
        return ("content_figure", f"mid-page inset ({int(width)}x{int(height)} px), no caption, possible figure")

    # 7) Square-ish + mid-sized + no caption -> probably a portrait photo.
    ratio = width / max(height, 1)
    if 0.7 <= ratio <= 1.4 and long_side < PORTRAIT_MAX_DIM_PX:
        return ("portrait", f"square-ish ({ratio:.2f}) and mid-size, no caption")

    # 8) Fallthrough -> conservative skip. Without a caption OR an obvious chart-
    # like geometric signal, we'd rather miss a real chart (-> README limitation)
    # than burn vision API on another lifestyle photo. v2 would add chart-shape
    # detection (axis-line counting via pixmap) to recover some of these.
    return ("decoration", f"no caption + no chart-shape signal ({int(width)}x{int(height)} px)")


# === Vision call ===========================================================

def _render_image_to_png(page: "fitz.Page", bbox: "fitz.Rect") -> bytes:
    """Render the bbox region from the page (not the embedded xref) so that
    (a) vector-drawn content is captured the same way raster images are,
    (b) the vision model sees exactly what a human reader sees,
    (c) we get a uniform PNG format for base64 encoding."""
    pixmap = page.get_pixmap(clip=bbox, dpi=VISION_RENDER_DPI, alpha=False)
    return pixmap.tobytes("png")


def _describe_with_vision(
    client: OpenAI,
    image_png: bytes,
    caption_hint: str | None,
) -> tuple[str, int, int]:
    """Single vision call. Returns (description, prompt_tokens, completion_tokens)
    so the caller can track real (not estimated) cost."""
    b64 = base64.b64encode(image_png).decode("ascii")
    prompt = VISION_PROMPT
    if caption_hint:
        # Passing the caption as additional context improves description quality
        # measurably -- the model knows what it's looking at instead of guessing.
        prompt += f"\n\nThe nearby caption is: {caption_hint!r}"
    resp = client.chat.completions.create(
        model=VISION_MODEL,
        temperature=0,  # deterministic so re-runs produce the same parsed.json
        max_tokens=VISION_MAX_OUTPUT_TOKENS,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{b64}",
                    "detail": VISION_DETAIL,
                }},
            ],
        }],
    )
    description = (resp.choices[0].message.content or "").strip()
    usage = resp.usage
    return description, usage.prompt_tokens, usage.completion_tokens


# === Composite-text builder ================================================

def _build_composite_text(page_data: dict) -> str:
    """Combine page text + tables (markdown) + vision-extracted figure
    descriptions into ONE blob. Step 2's chunker operates on this, so it
    doesn't need to know anything about multimodality -- the chart data is
    already in text form."""
    parts: list[str] = []
    if page_data["text"]:
        parts.append(page_data["text"])
    if page_data["tables_md"]:
        parts.append("\n\n--- Tables on this page ---")
        for i, tbl_md in enumerate(page_data["tables_md"], 1):
            parts.append(f"\n[Table {i}]\n{tbl_md}")
    # Inline only real figure descriptions; the vision model's fallback
    # strings ("DECORATION", "PHOTO: ...") shouldn't pollute the chunk.
    real_figures = []
    for img in page_data["images"]:
        if img["classification"] != "content_figure":
            continue
        desc = img.get("description")
        if not desc:
            continue
        if desc == "DECORATION" or desc.startswith("PHOTO:"):
            continue
        real_figures.append(img)
    if real_figures:
        parts.append("\n\n--- Figures on this page (vision-extracted) ---")
        for i, fig in enumerate(real_figures, 1):
            cap = f" (caption: {fig['caption_hint']!r})" if fig.get("caption_hint") else ""
            parts.append(f"\n[Figure {i}{cap}]\n{fig['description']}")
    return "\n".join(parts).strip()


# === Main orchestration ====================================================

def parse_pdf(
    src_doc: Doc,
    start_page: int = 0,
    limit_pages: int | None = None,
) -> dict:
    """Two-pass parse for a single Doc from DOCS.

    Pass 1 (cheap, no rendering): count how many pages each image xref
    appears on, so the router can detect repeated brand elements.

    Pass 2: extract text, tables, classify images, vision-call only the
    content figures.

    `start_page` and `limit_pages` are 0-indexed and primarily for smoke
    testing arbitrary page windows. Both default to "process the whole doc".
    """
    pdf_path = src_doc.path
    doc = fitz.open(pdf_path)
    total_pages_in_pdf = doc.page_count  # capture BEFORE closing the doc
    end_page = total_pages_in_pdf if limit_pages is None else min(total_pages_in_pdf, start_page + limit_pages)
    page_range = range(start_page, end_page)
    n_pages = len(page_range)
    print(f"[parse] [{src_doc.slug}] opened {pdf_path.name}: {total_pages_in_pdf} pages total, processing pages {start_page+1}-{end_page}")

    # ----- Pass 1: xref repetition counts -----
    # Only iterate the requested window: repetition counts should reflect
    # only the pages we'll actually parse (so a smoke test on pages 50-70
    # isn't biased by a brand strip that appears 200 times across the doc).
    xref_pages: dict[int, set[int]] = defaultdict(set)
    for pno in page_range:
        for img_info in doc[pno].get_images(full=True):
            xref = img_info[0]
            xref_pages[xref].add(pno)
    repetition = {xref: len(pages) for xref, pages in xref_pages.items()}
    print(f"[parse] pass 1: {len(repetition)} unique image xrefs across {n_pages} pages")

    # ----- Pass 2: full extraction -----
    client = OpenAI()  # reads OPENAI_API_KEY from env
    vision_calls = 0
    vision_failures = 0
    cum_input_tokens = 0
    cum_output_tokens = 0
    class_counter: Counter[str] = Counter()
    pages_data: dict[str, dict] = {}

    for pno in page_range:
        page = doc[pno]
        page_w, page_h = page.rect.width, page.rect.height
        text = _extract_text(page)
        tables_md = _extract_tables_md(page)

        images_data: list[dict] = []
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            for bbox in page.get_image_rects(xref):
                w, h = bbox.width, bbox.height
                caption = _find_nearby_caption(bbox, page)
                cls, reason = _classify_image(bbox, page_w, page_h, repetition[xref], caption)
                class_counter[cls] += 1

                img_record: dict = {
                    "xref": xref,
                    "bbox": [round(bbox.x0, 1), round(bbox.y0, 1),
                             round(bbox.x1, 1), round(bbox.y1, 1)],
                    "width_px": round(w, 1),
                    "height_px": round(h, 1),
                    "classification": cls,
                    "router_reason": reason,
                    "caption_hint": caption,
                }

                if cls == "content_figure":
                    try:
                        png = _render_image_to_png(page, bbox)
                        desc, in_tok, out_tok = _describe_with_vision(client, png, caption)
                        img_record["description"] = desc
                        cum_input_tokens += in_tok
                        cum_output_tokens += out_tok
                        vision_calls += 1
                    except Exception as e:
                        # Don't kill the parse on one bad image. Log to the
                        # record and continue; downstream code treats missing
                        # description as 'this figure was skipped'.
                        img_record["description"] = None
                        img_record["vision_error"] = str(e)[:200]
                        vision_failures += 1

                images_data.append(img_record)

        page_record = {
            "page_number": pno + 1,
            "text": text,
            "tables_md": tables_md,
            "images": images_data,
            "char_count": len(text),
        }
        page_record["composite_text"] = _build_composite_text(page_record)
        pages_data[str(pno + 1)] = page_record

        # Progress: print every 25 pages, and any page that triggered a
        # vision call (so the user can watch the interesting ones live).
        n_content = sum(1 for i in images_data if i["classification"] == "content_figure")
        if (pno + 1) % 25 == 0 or n_content > 0:
            est_cost = (cum_input_tokens / 1_000_000) * COST_PER_1M_INPUT_USD \
                     + (cum_output_tokens / 1_000_000) * COST_PER_1M_OUTPUT_USD
            print(
                f"[parse] p.{pno+1}/{total_pages_in_pdf}: "
                f"{len(text):>4} chars, {len(tables_md)} tables, "
                f"{len(images_data)} imgs ({n_content} content_figure)  "
                f"| cumulative: {vision_calls} vision calls, ~${est_cost:.4f}"
            )

    doc.close()

    final_est_cost = (cum_input_tokens / 1_000_000) * COST_PER_1M_INPUT_USD \
                   + (cum_output_tokens / 1_000_000) * COST_PER_1M_OUTPUT_USD

    return {
        "source_doc": {
            "slug": src_doc.slug,
            "display": src_doc.display,
            "fiscal_year_ending": src_doc.fiscal_year_ending,
            "pdf_path": str(pdf_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        },
        "page_count_total": total_pages_in_pdf,
        "page_count_parsed": n_pages,
        "page_range_parsed": [start_page + 1, end_page],
        "ingested_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "router_config": {
            "min_content_dim_px": MIN_CONTENT_DIM_PX,
            "max_decoration_aspect": MAX_DECORATION_ASPECT,
            "brand_repetition_threshold": BRAND_REPETITION_THRESHOLD,
            "caption_lookahead_px": CAPTION_LOOKAHEAD_PX,
            "portrait_max_dim_px": PORTRAIT_MAX_DIM_PX,
        },
        "vision_config": {
            "model": VISION_MODEL,
            "detail": VISION_DETAIL,
            "render_dpi": VISION_RENDER_DPI,
        },
        "stats": {
            "image_classifications": dict(class_counter),
            "vision_calls": vision_calls,
            "vision_failures": vision_failures,
            "vision_input_tokens": cum_input_tokens,
            "vision_output_tokens": cum_output_tokens,
            "vision_cost_usd_estimate": round(final_est_cost, 4),
        },
        "pages": pages_data,
    }


def _parse_one(src_doc: Doc, start_page: int, limit_pages: int | None) -> None:
    if not src_doc.path.exists():
        sys.exit(f"[parse] PDF not found at {src_doc.path}. Drop it there and re-run.")
    out_path = parsed_json_path(src_doc.slug)
    print(f"[parse] [{src_doc.slug}] output -> {out_path}")
    t0 = time.time()
    out = parse_pdf(src_doc, start_page=start_page, limit_pages=limit_pages)
    elapsed = time.time() - t0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    sz_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"[parse] [{src_doc.slug}] DONE in {elapsed:.1f}s, wrote {out_path.name} ({sz_mb:.2f} MB)")
    print(f"[parse] [{src_doc.slug}] image classifications: {out['stats']['image_classifications']}")
    print(
        f"[parse] [{src_doc.slug}] vision: {out['stats']['vision_calls']} calls, "
        f"{out['stats']['vision_failures']} failures, "
        f"~${out['stats']['vision_cost_usd_estimate']:.4f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse one or all Infosys annual-report PDFs.")
    parser.add_argument(
        "--doc", type=str, default=None,
        help=f"Parse only this doc slug; default = all of {[d.slug for d in DOCS]}.",
    )
    parser.add_argument(
        "--start", type=int, default=1,
        help="1-indexed page number to start from (smoke-test helper).",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Parse only N pages starting at --start (smoke-test helper).",
    )
    args = parser.parse_args()

    targets = [DOCS_BY_SLUG[args.doc]] if args.doc else list(DOCS)
    if args.doc and args.doc not in DOCS_BY_SLUG:
        sys.exit(f"[parse] unknown --doc '{args.doc}'. Known: {list(DOCS_BY_SLUG)}")

    for src_doc in targets:
        _parse_one(src_doc, start_page=max(0, args.start - 1), limit_pages=args.limit)


if __name__ == "__main__":
    main()
