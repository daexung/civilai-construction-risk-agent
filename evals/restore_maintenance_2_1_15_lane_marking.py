"""Restore the omitted manual paint table and route method-specific line marking crews."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/drafts/specs/유지관리/2-1-15.json"
package = json.loads(PATH.read_text(encoding="utf-8"))
draft = package["draft"]
tables = {item["id"]: item for item in draft["tables"]}
manual = tables["p938-t2"]
manual["role"] = "2. 수용성형 페인트 수동식 작업조, 일당시공량 및 비고"
manual["source"] = "PDF 882쪽 2-1-15 2. 수용성형 페인트 수동식 표"
manual["values"] = {
    "특별인부": {"단위": "인", "수량": "2"},
    "보통인부": {"단위": "인", "수량": "2", "시공량(㎡) 실선": "600",
                  "시공량(㎡) 파선": "300", "시공량(㎡) 횡단보도,\n주차장": "228",
                  "시공량(㎡) 문자,\n기호": "108"},
    "트럭": {"규격": "4.5ton", "단위": "대", "수량": "1"},
    "비고": {"- 노면에 표지병 등이 설치되어 작업능률이 저하되는 경우에는 시공량을 10%까지 감하여 적용한다.": ""},
}
tables["p939-t0"]["values"]["트럭"] = {"규격": "2.5ton", "단위": "대", "수량": "1"}
tables["p939-t0"]["source"] = "PDF 883쪽 2-1-15 3. 수용성형 페인트 기계식 표; 파싱에서 누락된 2.5ton 트럭 행 복구"
table_for_method = {
    "차선 밑그림": "p938-t1",
    "수용성형 페인트 수동식": "p938-t2",
    "수용성형 페인트 기계식": "p939-t0",
    "융착식 도료 수동식": "p939-t1",
    "상온경화형 플라스틱 도료 구동식": "p940-t2",
}
for table_id, printed_page in (("p938-t1", 882), ("p939-t0", 883), ("p939-t1", 883), ("p940-t2", 884)):
    tables[table_id]["source"] = f"PDF {printed_page}쪽 2-1-15 {tables[table_id]['role']}"

type_columns = {
    "실선": "실선", "파선": "파선",
    "횡단보도, 주차장": "횡단보도, 주차장", "문자, 기호": "문자, 기호",
}
draft["quantity_model"] = {
    "name": "adjusted_daily_crew",
    "params": {
        "base_output": {"table": "p938-t1", "table_selector": {
            "input": "method", "values": table_for_method},
            "row": "보통인부", "column_selector": {"input": "line_type",
                "contains": ["시공량(㎡) {value}"], "value_map": type_columns}},
        "coefficients": [],
        "crew": {"table": "p938-t1", "table_selector": {
            "input": "method", "values": table_for_method},
            "trades": ["특별인부", "보통인부"], "column": "수량"},
        "equipment": [
            {"table": "p938-t1", "table_selector": {"input": "method", "values": table_for_method},
             "name": item["name"], "row": item["row"], "column": "수량", "unit": "대·일",
             "when": {"method": item["method"]}}
            for item in [
                {"method": "차선 밑그림", "name": "트럭(2.5ton)", "row": "트럭"},
                {"method": "수용성형 페인트 수동식", "name": "트럭(4.5ton)", "row": "트럭"},
                {"method": "수용성형 페인트 기계식", "name": "라인마커트럭(10㎞/hr)", "row": "라인마커트럭"},
                {"method": "수용성형 페인트 기계식", "name": "트럭(2.5ton)", "row": "트럭"},
                {"method": "융착식 도료 수동식", "name": "트럭(4.5ton, 용해기 운반)", "row": "트럭"},
                {"method": "융착식 도료 수동식", "name": "트럭(2.5ton, 자재·경장비 운반)", "row": "트럭 "},
                {"method": "상온경화형 플라스틱 도료 구동식", "name": "트럭(2.5ton)", "row": "트럭"},
            ]
        ],
        "quantity_input": "quantity",
    },
    "steps": [
        "공법에 따라 해당 원문 일당표 p938-t1, p938-t2, p939-t0, p939-t1 또는 p940-t2를 선택한다.",
        "도색 종류의 시공량 열에서 일당 시공량을 선택하고 같은 표에서 직종 수량과 해당 공법의 장비를 읽는다.",
        "작업일수 = 면적 물량 ÷ 원문 일당시공량으로 계산하고 작업조 및 장비 수량을 곱한다.",
        "표지병 등으로 작업능률이 저하되는 경우 원문은 시공량을 ‘10%까지’ 감하도록 허용하나 고정 감산률은 정하지 않으므로 해당 조건은 자동 계산을 보류한다.",
        "공법별 원문에 있는 기계경비 요율은 cost_rules에 조건별로 연결한다; 차량우회, 사전청소, 소모재료 및 별도 도료량은 별도 계상으로 유지한다.",
    ],
    "source": "PDF 882~884쪽 2-1-15 차선도색 다섯 공법 표와 주",
    "rounding": "총 투입량은 정확한 유리수로 보존; 단위당 품은 공통 1-2-8·1-2-1 기본 자릿수 적용",
}
draft["blocked"] = [
    {"condition": "표지병 등으로 인한 작업능률 저하의 감산 폭 미확정",
     "reason": "원문은 해당 공법의 시공량을 ‘10%까지’ 감하도록 허용하지만 적용할 고정 감산 폭은 지정하지 않는다.",
     "source": "PDF 882~884쪽 2-1-15 각 공법 비고",
     "blocked_if_all": [{"input": "method", "op": "in", "value": list(table_for_method)[1:]},
                        {"input": "surface_obstacle", "op": "==", "value": True}],
     "cite": {"page_source": {"pdf_page": 938, "printed_page": 882, "section_no": "2-1-15",
                               "section_title": "차선도색", "item": "2. 수용성형 페인트 수동식 비고"}}},
    {"condition": "수용성형 페인트 기계식에 횡단보도·문자 시공량 셀이 없음",
     "reason": "기계식 원문표에는 실선과 파선 시공량만 있어 나머지 두 line_type 조합에 대응하는 수치가 없다.",
     "source": "PDF 883쪽 2-1-15 3. 수용성형 페인트 기계식 표",
     "blocked_if_all": [{"input": "method", "op": "==", "value": "수용성형 페인트 기계식"},
                        {"input": "line_type", "op": "not_in", "value": ["실선", "파선"]}],
     "cite": {"table_id": "p939-t0"}},
]
draft["crew_rules"] = []
draft["cost_rules"] = [
    {"name": "라인마커 및 경장비 기계경비", "category": "경비", "base": "labor_subtotal",
     "rate": "0.03", "when": {"method": "수용성형 페인트 수동식"}, "source": "PDF 883쪽 주 ⑧",
     "cite": {"chunk_id": "p939-x0", "quote": "⑧ 공구손료 및 경장비(라인마커 등)의 기계경비는 인력품의 3%로 계상한다."}},
    {"name": "라인마커·용해기 및 경장비 기계경비", "category": "경비", "base": "labor_subtotal",
     "rate": "0.10", "when": {"method": "융착식 도료 수동식"}, "source": "PDF 883쪽 주 ⑧",
     "cite": {"chunk_id": "p940-x2", "quote": "⑧ 공구손료 및 경장비(라인마커, 용해기 등)의 기계경비는 인력품의 10%로 계상한다."}},
    {"name": "핸드믹서 등 공구손료 및 경장비 기계경비", "category": "경비", "base": "labor_subtotal",
     "rate": "0.02", "when": {"method": "상온경화형 플라스틱 도료 구동식"}, "source": "PDF 884쪽 주 ⑥",
     "cite": {"chunk_id": "p940-x11", "quote": "⑥ 공구손료 및 경장비(핸드믹서 등)의 기계경비는 인력품의 2%로 계상하고, 라인마커의 기계경비는 별도 계상한다."}},
]
draft["not_calculated"] = [item for item in draft.get("not_calculated", [])
                           if item.get("item") != "공구손료 및 기계경비"]
draft["not_calculated"].append({
    "item": "탑승형 라인마커 기계경비 별도 계상",
    "source": "PDF 884쪽 2-1-15 주 ⑥",
    "when": {"method": "상온경화형 플라스틱 도료 구동식"},
    "cite": {"chunk_id": "p940-x11",
             "quote": "⑥ 공구손료 및 경장비(핸드믹서 등)의 기계경비는 인력품의 2%로 계상하고, 라인마커의 기계경비는 별도 계상한다."},
})
draft["open_questions"] = [
    "수용성형 페인트 기계식은 일당 시공량을 실선·파선만 제공하며 횡단보도·주차장 및 문자·기호 값은 원문에 없다. 해당 조합은 보류 규칙에 둔다.",
    "표지병 등 작업능률 저하 시 ‘10%까지’ 감산은 범위 허용으로 읽히며 고정 감산률이 없어 obstacle=true 입력은 보류한다.",
]
package["open_questions"] = list(draft["open_questions"])
draft["calc_type_reason"] = "다섯 공법의 일당 기준표를 method별 table selector로 연결하고, 파싱에서 누락된 수용성형 수동식 표를 PDF 882쪽 원문 값으로 복원했다. 공법별 명시 기계경비 요율은 조건부 cost_rules로 연결했다. 표지병 감산 폭과 기계식 표에 없는 line_type 조합은 임의 값 없이 보류한다."
package["calc_type"] = "daily_crew"
PATH.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("reconstructed", draft["id"])
