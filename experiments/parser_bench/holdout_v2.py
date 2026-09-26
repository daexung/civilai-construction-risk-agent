"""Select and render a fresh, source-only holdout for the next G7 decision.

This module never imports a parser or reads parser output.  Selection is
deterministic; rendering only opens the original PDF.
"""

import json
import random
import sys

import pymupdf

from common import PDF, RESULTS, save_json

SEED = "holdout-v2-2026-09-25"
TOTAL_PAGES = 982
OUT = RESULTS / "holdout_v2"


def previous_candidates() -> set[int]:
    """Conservatively exclude even viewed or rendered unused P5 candidates."""
    old = json.loads((RESULTS / "holdout/selection.json").read_text(encoding="utf-8"))
    return set(old["random_order"]) | set(old["targeted_pool"])


def seen_pages() -> set[int]:
    seen = set(range(185, 215)) | previous_candidates()
    for cohort in ("validation", "blind20"):
        selection = json.loads((RESULTS / cohort / "selection.json").read_text(encoding="utf-8"))
        seen.update(selection["pages"])
    return seen


def select() -> dict:
    seen = seen_pages()
    excluded = {p + delta for p in seen for delta in (-1, 0, 1)}
    allowed = [p for p in range(1, TOTAL_PAGES + 1) if p not in excluded]
    rng = random.Random(SEED)
    width = len(allowed) / 20
    random_order = [rng.choice(allowed[int(i * width):int((i + 1) * width)])
                    for i in range(20)]
    rng.shuffle(random_order)
    # Keep the target pool away from the random group, including adjacent
    # pages that may continue the same table.
    near_random = {p + delta for p in random_order for delta in (-1, 0, 1)}
    rest = [p for p in allowed if p not in near_random]
    targeted_pool = sorted(rng.sample(rest, 32))
    result = {
        "seed": SEED,
        "pdf_pages": TOTAL_PAGES,
        "excluded_source": [
            "pilot pages 185-214", "validation selection", "blind20 selection",
            "all 20 P5 random candidates", "all 32 P5 targeted candidates",
        ],
        "exclusion_radius": 1,
        "seen_pages": sorted(seen),
        "excluded_count": len(excluded & set(range(1, TOTAL_PAGES + 1))),
        "rule": "20 strata, one seeded page each, shuffled reading order; take pages until at least 15 source tables. Separate 32-page seeded target pool; choose 2-3 diagonal-header and 2-3 long borderless tables from thumbnails. Exclude all prior candidate pages and their neighbors. Use source images only before truth freeze.",
        "random_order": random_order,
        "targeted_pool": targeted_pool,
    }
    save_json(OUT / "selection.json", result)
    return result


def render_pages(pages: list[int]) -> None:
    (OUT / "pages").mkdir(parents=True, exist_ok=True)
    with pymupdf.open(PDF) as doc:
        for page_no in pages:
            doc[page_no - 1].get_pixmap(dpi=110).save(OUT / "pages" / f"p{page_no}.png")
    print(f"Rendered {len(pages)} source pages")


def render_sheets() -> None:
    selection = json.loads((OUT / "selection.json").read_text(encoding="utf-8"))
    (OUT / "sheets").mkdir(parents=True, exist_ok=True)
    pool = selection["targeted_pool"]
    with pymupdf.open(PDF) as doc:
        w, h = doc[0].rect.width, doc[0].rect.height
        for start in range(0, len(pool), 8):
            sheet = pymupdf.open()
            canvas = sheet.new_page(width=w * 4, height=(h + 20) * 2)
            for index, page_no in enumerate(pool[start:start + 8]):
                x = (index % 4) * w
                y = (index // 4) * (h + 20)
                canvas.show_pdf_page(pymupdf.Rect(x, y + 20, x + w, y + 20 + h), doc, page_no - 1)
                canvas.insert_text((x + 10, y + 16), f"p{page_no}", fontsize=18, color=(1, 0, 0))
            canvas.get_pixmap(dpi=40).save(OUT / "sheets" / f"sheet{start // 8 + 1}.png")
            sheet.close()
    print("Rendered 4 target-pool thumbnail sheets")


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "select":
        print(json.dumps(select(), ensure_ascii=False))
    elif action == "render":
        selection = json.loads((OUT / "selection.json").read_text(encoding="utf-8"))
        render_pages([int(p) for p in sys.argv[2:]] or selection["random_order"])
    elif action == "sheets":
        render_sheets()
    else:
        raise SystemExit(f"Unknown action: {action}")
