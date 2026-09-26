"""P5 보류 표본: 아직 보지 않은 쪽에서 표를 골라 정답을 먼저 고정하고, 파이프라인을 한 번만 돌린다.

순서 (docs/ODL_MIGRATION_PLAN.md 4-2):
  select : 쪽 고정 → results/holdout/selection.json   ※ 파서 미사용
  render : 무작위 후보 쪽 렌더링(세로 좌표 눈금) → results/holdout/pages/
  sheets : 표적 후보 쪽 축소 이미지 모음 → results/holdout/sheets/ (대각선 머리칸·가로선 없는 긴 표 고르기용)
  (원문 이미지만 보고 results/holdout/ground_truth.json 작성)
  crops  : 정답 표마다 원문 조각 → results/holdout/crops/ (사람 확인용)
  (사용자가 표 5개 대조 → 정답 커밋 → 파이프라인 1회 실행)

제외 쪽: 지금까지 본 쪽과 그 앞뒤 쪽(이어지는 표 때문)
  - 185~214(파일럿 장·5표·23건), 검증 10쪽, blind20 20쪽
무작위: 남은 쪽을 20구간으로 나눠 구간마다 1쪽을 뽑고, 그 20쪽의 순서를 시드로 섞는다.
        섞인 순서대로 쪽을 보며 정답 표가 15개 이상이 될 때까지 쓴다(그 뒤 쪽은 쓰지 않는다).
표적: 무작위 20쪽과 겹치지 않게 32쪽을 따로 뽑아 축소 이미지만 보고,
      대각선 머리칸 표 2~3개와 가로선 없는 긴 표 2~3개를 고른다.
"""
import json
import random
import sys

import pymupdf

from common import PDF, RESULTS, save_json

SEED = "holdout-2026-09-24"
TOTAL_PAGES = 982
OUT = RESULTS / "holdout"


def seen_pages() -> set[int]:
    seen = set(range(185, 215))
    seen |= set(json.loads((RESULTS / "validation" / "selection.json").read_text(encoding="utf-8"))["pages"])
    seen |= set(json.loads((RESULTS / "blind20" / "selection.json").read_text(encoding="utf-8"))["pages"])
    return seen


def select() -> dict:
    seen = seen_pages()
    excluded = {p + d for p in seen for d in (-1, 0, 1)}
    allowed = [p for p in range(1, TOTAL_PAGES + 1) if p not in excluded]
    rng = random.Random(SEED)
    size = len(allowed) / 20
    random_pages = [rng.choice(allowed[int(i * size): int((i + 1) * size)]) for i in range(20)]
    rng.shuffle(random_pages)
    rest = [p for p in allowed if p not in random_pages]
    targeted_pool = sorted(rng.sample(rest, 32))
    out = {
        "seed": SEED,
        "rule": "본 쪽(185~214, 검증 10쪽, blind20)과 앞뒤 쪽 제외. 무작위 20쪽(20구간 층화 후 순서 섞음)을 순서대로 보며 "
                "정답 표 15개 이상이 될 때까지 사용. 표적 후보 32쪽은 축소 이미지만 보고 대각선 머리칸·가로선 없는 긴 표를 고름",
        "excluded_count": len(excluded & set(range(1, TOTAL_PAGES + 1))),
        "random_order": random_pages,
        "targeted_pool": targeted_pool,
    }
    save_json(OUT / "selection.json", out)
    return out


def render() -> None:
    sel = json.loads((OUT / "selection.json").read_text(encoding="utf-8"))
    (OUT / "pages").mkdir(parents=True, exist_ok=True)
    pages = [int(a) for a in sys.argv[2:]] or sel["random_order"]
    with pymupdf.open(PDF) as doc:
        for p in pages:
            tmp = pymupdf.open()
            tmp.insert_pdf(doc, from_page=p - 1, to_page=p - 1)
            tp = tmp[0]
            for y in range(0, int(tp.rect.height), 50):
                tp.draw_line((0, y), (40, y), color=(1, 0, 0), width=0.6)
                tp.insert_text((2, y - 1), str(y), fontsize=7, color=(1, 0, 0))
            tp.get_pixmap(dpi=110).save(OUT / "pages" / f"p{p}.png")
            tmp.close()
    print(f"{len(pages)}쪽 렌더링")


def sheets() -> None:
    """표적 후보 32쪽을 8쪽씩 한 장의 축소 이미지로 묶는다."""
    sel = json.loads((OUT / "selection.json").read_text(encoding="utf-8"))
    (OUT / "sheets").mkdir(parents=True, exist_ok=True)
    pool = sel["targeted_pool"]
    with pymupdf.open(PDF) as doc:
        w, h = doc[0].rect.width, doc[0].rect.height
        for s in range(0, len(pool), 8):
            sheet = pymupdf.open()
            page = sheet.new_page(width=w * 4, height=h * 2 + 40)
            for k, p in enumerate(pool[s:s + 8]):
                x, y = (k % 4) * w, (k // 4) * (h + 20)
                page.show_pdf_page(pymupdf.Rect(x, y + 20, x + w, y + 20 + h), doc, p - 1)
                page.insert_text((x + 10, y + 16), f"p{p}", fontsize=18, color=(1, 0, 0))
            page.get_pixmap(dpi=40).save(OUT / "sheets" / f"sheet{s // 8 + 1}.png")
            sheet.close()
    print("축소 이미지", (len(pool) + 7) // 8, "장")


def crops() -> None:
    gt = json.loads((OUT / "ground_truth.json").read_text(encoding="utf-8"))
    (OUT / "crops").mkdir(parents=True, exist_ok=True)
    with pymupdf.open(PDF) as doc:
        for t in gt["tables"]:
            page = doc[t["page"] - 1]
            b = t["bbox_pt"]
            clip = pymupdf.Rect(0, max(0, b[1] - 8), page.rect.width, min(page.rect.height, b[3] + 8))
            page.get_pixmap(clip=clip, dpi=150).save(OUT / "crops" / f"{t['id']}.png")
    print(f"표 {len(gt['tables'])}개 조각")


if __name__ == "__main__":
    {"select": lambda: print(json.dumps(select(), ensure_ascii=False)), "render": render,
     "sheets": sheets, "crops": crops}[sys.argv[1]]()
