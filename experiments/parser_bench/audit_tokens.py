"""숫자·단위 오독 점검. PDF 텍스트 레이어를 정답으로 두고, 각 파서의 쪽 전체 출력과 비교한다.

- 지정 토큰(0.013, 0.02, ㎥/hr, ℓ, (100㎡당) 등)의 개수: 정확 일치 / 표기 변형 / 누락
- 쪽 안의 소수(예: 0.12, 4.5) 전체를 다중집합으로 비교해 빠진 값과 원문에 없는 값을 찾는다
- 변형·기준 단어 주변 문맥을 함께 남긴다

실행(저장소 루트, 기존 .venv): python experiments/parser_bench/audit_tokens.py
"""
import json
import re
from collections import Counter

import pymupdf

from common import PAGES_DIR, RESULTS, save_json

TARGETS = [
    # (쪽, 토큰, 종류, 표기 변형, 문맥을 볼 기준 단어)
    (186, "㎥/hr", "unit", ["m³/hr", "m3/hr", "m^3/hr", "㎥/h", "m³/h", "m3/h", "m²/hr"], "펌프차"),
    (188, "0.013", "number", ["0.13", "0.0013", "0,013", ".013", "0.018", "0.015", "0.01"], "품질관리"),
    # 0.2는 같은 쪽 시너 수량(정상값)과 겹쳐 변형 목록에서 뺀다. 소수 다중집합 비교에서 따로 잡힌다
    (188, "0.02", "number", ["0.002", "0,02", ".02", "0.03", "0.05"], "치핑"),
    (188, "ℓ", "unit", ["l", "L"], "시너"),
    (193, "(100㎡당)", "unit", ["(100m²당)", "(100m2당)", "(100m^2당)", "100㎡당", "(100㎡)", "(100m²)"], "인력 설치"),
    (185, "(0.6∼0.8㎥)", "unit", ["(0.6~0.8㎥)", "(0.6∼0.8m³)", "(0.6~0.8m³)", "(0.6~0.8m3)", "(0.6-0.8㎥)"], "굴착기"),
    # 0.12는 같은 쪽 특별인부 수량(정상값)과 겹쳐 변형 목록에서 뺀다
    (188, "0.12인", "number", ["0.12명", "0.12입", "0.121"], "도장공"),
]


def ws(text) -> str:
    return re.sub(r"\s+", "", text or "")


def spaced(text) -> str:
    # 숫자는 공백·줄바꿈을 구분자로 남겨야 한다. 지우면 쌓인 칸 '0.12\n0.02'가 '0.120.02'로 붙는다
    return re.sub(r"\s+", " ", text or "")


def count_token(text: str, token: str, kind: str) -> int:
    if kind == "number":
        m = re.fullmatch(r"([\d.]+)(.*)", token)
        number, unit = m.group(1), m.group(2)
        pattern = rf"(?<![\d.]){re.escape(number)}(?![\d])" + (rf"\s?{re.escape(unit)}" if unit else "")
        return len(re.findall(pattern, spaced(text)))
    if token in ("l", "L"):
        return len(re.findall(rf"(?<![A-Za-z]){token}(?![A-Za-z])", spaced(text)))
    return ws(text).count(ws(token))


def decimals(text: str) -> Counter:
    return Counter(re.findall(r"(?<![\d.])\d+\.\d+(?![\d.])", spaced(text)))


def contexts(text: str, needle: str, width: int = 30, limit: int = 3) -> list[str]:
    flat = re.sub(r"\s+", " ", text)
    out = []
    for m in re.finditer(re.escape(needle), flat):
        out.append(flat[max(0, m.start() - 8): m.end() + width])
        if len(out) >= limit:
            break
    return out


def odl_text(path) -> str:
    parts = []

    def walk(n):
        if isinstance(n, dict):
            if isinstance(n.get("content"), str):
                parts.append(n["content"])
            for k in ("kids", "rows", "cells", "list items"):
                for c in n.get(k, []) or []:
                    walk(c)
        elif isinstance(n, list):
            for c in n:
                walk(c)

    walk(json.loads(path.read_text(encoding="utf-8")))
    return "\n".join(parts)


def page_text(run: str, page: int) -> str | None:
    raw = RESULTS / run / "raw"
    if run.startswith("docling"):
        p = raw / f"p{page}.md"
        return p.read_text(encoding="utf-8") if p.exists() else None
    if run.startswith("odl"):
        p = raw / f"p{page}.json"
        return odl_text(p) if p.exists() else None
    if run.startswith("paddle"):
        p = raw / f"p{page}_page_text.txt"
        return p.read_text(encoding="utf-8") if p.exists() else None
    return None


def main() -> None:
    runs = sorted(d.name for d in RESULTS.iterdir() if d.is_dir() and (d / "tables.json").exists() and d.name != "pymupdf")
    truth = {}
    for page in sorted({t[0] for t in TARGETS}):
        with pymupdf.open(PAGES_DIR / f"p{page}.pdf") as doc:
            truth[page] = doc[0].get_text()

    report = {"truth_source": "PyMuPDF get_text() 텍스트 레이어", "targets": [], "decimals": {}}
    for page, token, kind, variants, anchor in TARGETS:
        row = {"page": page, "token": token, "expected": count_token(truth[page], token, kind), "runs": {}}
        for run in runs:
            text = page_text(run, page)
            if text is None:
                row["runs"][run] = None
                continue
            found = count_token(text, token, kind)
            # 공백만 다른 변형은 정확 일치와 같으므로 제외. 정답 토큰의 일부인 변형(㎥/h ⊂ ㎥/hr)은
            # 정답 등장분을 빼야 순수 변형 개수가 된다
            var = {}
            for v in variants:
                if ws(v) == ws(token):
                    continue
                n = count_token(text, v, "number" if re.match(r"[\d.]", v) else "unit")
                if ws(v) in ws(token):
                    n -= found
                var[v] = max(n, 0)
            row["runs"][run] = {
                "exact": found,
                "variants": {v: n for v, n in var.items() if n},
                "anchor_context": contexts(text, anchor),
            }
        report["targets"].append(row)

    for page in truth:
        gt = decimals(truth[page])
        report["decimals"][page] = {"truth": sorted(gt.elements())}
        for run in runs:
            text = page_text(run, page)
            if text is None:
                continue
            got = decimals(text)
            report["decimals"][page][run] = {
                # 오독 판정: 원문 쪽 어디에도 없는 값 / 원문에 있는데 한 번도 안 나온 값
                "not_in_source": sorted(set(got) - set(gt)),
                "never_output": sorted(set(gt) - set(got)),
                # 참고: 개수 차이. 병합 칸 값을 칸마다 반복하는 출력 형식이면 '많음'이 생긴다
                "count_short": sorted((gt - got).elements()),
                "count_extra": sorted((got - gt).elements()),
            }

    save_json(RESULTS / "token_audit.json", report)
    for row in report["targets"]:
        print(f"\n[p{row['page']}] {row['token']}  원문 {row['expected']}건")
        for run, r in row["runs"].items():
            if r is None:
                print(f"   {run:26s} (출력 없음)")
                continue
            print(f"   {run:26s} 정확 {r['exact']}  변형 {r['variants'] or '-'}")
    print("\n[소수 값 비교] 오독 후보 = 원문에 없는 값 / 누락 = 원문 값이 한 번도 안 나옴 / 개수 차이는 참고")
    for page, d in report["decimals"].items():
        for run, r in d.items():
            if run == "truth":
                continue
            if r["not_in_source"] or r["never_output"] or r["count_short"]:
                print(f"   p{page} {run:26s} 원문에없음 {r['not_in_source']}  한번도없음 {r['never_output']}  "
                      f"개수부족 {r['count_short']}")


if __name__ == "__main__":
    main()
