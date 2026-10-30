"""미지원으로 분류됐던 초안 중 기존 계산기로 표현되는 절을 원문 표·비고 그대로 연결한다.

각 승격은 PDF 원문(쪽 번호 기록)과 대조해 작성했다. 외부 호출 없음, 재실행해도 결과가 같다(멱등).
검증은 evals/check_promoted_unsupported_calc.py가 원문에서 따로 계산한 기대값으로 한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.validate_drafts import chunks_by_id_from_list, validate_one  # noqa: E402

SPECS = ROOT / "data/drafts/specs"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
PROMOTIONS: dict[str, callable] = {}


def promotion(key: str):
    def register(function):
        PROMOTIONS[key] = function
        return function
    return register

def refresh_table_citations(package: dict, table_id: str) -> list[str]:
    """교체한 표의 패키지 인용을 새 (행, 열, 값)으로 다시 만든다. 청크 텍스트에 없는 칸은 인용하지 않고 돌려준다."""
    from pipeline.validate_drafts import check_table_citation
    global _CHUNK_INDEX
    if _CHUNK_INDEX is None:
        _CHUNK_INDEX = chunks_by_id_from_list(
            [json.loads(l) for l in CHUNKS.read_text(encoding="utf-8").splitlines() if l.strip()])
    package["citations"] = [c for c in package["citations"] if c.get("table_id") != table_id]
    table = next(t for t in package["draft"]["tables"] if t["id"] == table_id)
    missing = []
    for row, cells in table["values"].items():
        for column, value in cells.items():
            citation = {"table_id": table_id, "row": row, "column": column, "value": value}
            if check_table_citation(_CHUNK_INDEX, citation):
                missing.append(f"{row}/{column}={value}")
            else:
                package["citations"].append(citation)
    return missing


_CHUNK_INDEX: dict | None = None


def _walk_quotes(value):
    if isinstance(value, dict):
        if isinstance(value.get("chunk_id"), str) and isinstance(value.get("quote"), str):
            yield value
        for child in value.values():
            yield from _walk_quotes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_quotes(child)


def repair_line_crossing_quotes(package: dict, index: dict) -> int:
    """청크 텍스트에는 줄바꿈 표지('설명 |')가 끼어 인용문이 줄을 넘으면 검증에 실패한다.
    실패한 인용문은 줄 단위 조각 중 청크에 그대로 있는 가장 긴 조각만 남긴다(문장을 바꾸지 않는다)."""
    from pipeline.validate_drafts import check_text_citation
    from pipeline.validate_drafts import check_table_citation
    changed = 0
    for cite in package.get("citations", []):
        if "table_id" in cite and cite.get("value") and check_table_citation(index, cite):
            words = str(cite["value"]).split(" ")
            while len(words) > 1:
                words.pop()
                if not check_table_citation(index, {**cite, "value": " ".join(words)}):
                    cite["value"] = " ".join(words)  # 청크에 그대로 있는 앞부분만 남긴다
                    changed += 1
                    break
            else:
                cite.pop("value", None)
                changed += 1
    for cite in _walk_quotes(package):
        if not check_text_citation(index, cite):
            continue
        pieces = sorted((p for p in cite["quote"].splitlines() if p.strip()), key=len, reverse=True)
        for piece in pieces:
            if not check_text_citation(index, {**cite, "quote": piece}):
                cite["quote"] = piece
                changed += 1
                break
        else:
            # 줄바꿈 표지가 문장 중간에 끼인 경우: 청크에 그대로 있는 가장 긴 앞부분을 남긴다.
            words = " ".join(cite["quote"].split()).split(" ")
            while len(words) > 3:
                words.pop()
                if not check_text_citation(index, {**cite, "quote": " ".join(words)}):
                    cite["quote"] = " ".join(words)
                    changed += 1
                    break
    return changed


def defer(package: dict, reason: str) -> None:
    """계산 연결을 보류한다: 복원한 표·입력은 남기고 계산 방식만 not_calculable로 되돌린다(공통 기능 부족 기록)."""
    spec = package["draft"]
    steps = spec["quantity_model"].get("steps", [])
    package["calc_type"] = "not_calculable"
    package["calc_type_reason"] = reason
    spec["quantity_model"] = {"name": "not_calculable", "params": {}, "steps": steps,
                              "source": spec["quantity_model"].get("source", ""), "rounding": "해당 없음"}


def field(spec: dict, name: str) -> dict:
    return next(item for item in spec["inputs"] if item["name"] == name)


def upsert_input(spec: dict, item: dict) -> None:
    for index, current in enumerate(spec["inputs"]):
        if current["name"] == item["name"]:
            spec["inputs"][index] = item
            return
    spec["inputs"].append(item)


def finish(package: dict, calc_type: str, reason: str, steps: list[str], params: dict, *,
           model: str = "adjusted_daily_crew", source: str) -> None:
    spec = package["draft"]
    package["calc_type"] = calc_type
    package["calc_type_reason"] = reason
    package["open_questions"] = [q for q in package.get("open_questions", []) if "equipment 파라미터" not in q]
    spec["quantity_model"] = {"name": model, "params": params, "steps": steps, "source": source,
                              "rounding": "총 투입량은 정확한 유리수로 보존; 단위당 품은 공통 1-2-8·1-2-1 기본 자릿수 적용"}


def concrete_surface_paving(package: dict, table: str, output_row: str, thickness_page: str) -> None:
    """1-6-3/1-6-4: 인원·장비 대수 표 + 포장 종류별 일당 시공량 + 공항포장 15% 감 + 두께 50cm 제한."""
    spec = package["draft"]
    upsert_input(spec, {**field(spec, "frequent_movement"), "when": {"input": "pavement_type", "equals": "공항포장"},
                        "ask": "공항포장에서 집수정, 기초 등 지장물로 이동이 빈번하여 연속 포설이 불가능합니까?"})
    upsert_input(spec, {"name": "pavement_thickness", "type": "positive_rational", "allowed_values": "0보다 큰 수",
                        "unit": "cm", "required": True, "when": {"input": "pavement_type", "equals": "공항포장"},
                        "ask": "공항포장의 포장두께는 몇 cm입니까?", "source": f"{thickness_page} [주] ②"})
    spec["blocked"] = [
        {"condition": "공항포장이며 포장두께가 50cm를 초과하는 경우",
         "blocked_if_all": [{"input": "pavement_type", "op": "==", "value": "공항포장"},
                            {"input": "pavement_thickness", "op": ">", "value": "50"}],
         "reason": "공항포장은 포장두께 50cm 이하 포설 기준입니다.", "source": f"{thickness_page} [주] ②",
         "cite": {"table_id": table}}]
    crew = ["포장공", "특별인부", "보통인부"]
    params = {
        "quantity_input": "volume",
        "base_output": {"table": table, "row": output_row, "column_input": "pavement_type"},
        "coefficients": [],
        "crew": {"table": table, "column": "수량", "trades": crew, "rate_codes": {name: "" for name in crew}},
        "equipment": [{"name": name, "table": table, "column": "수량", "unit": "대·일"}
                      for name in ("콘크리트페이버", "굴착기", "살수차")],
        "output_adjustments": [{
            "when": {"pavement_type": "공항포장", "frequent_movement": True},
            "operation": "set_output_percent", "value": "15",
            "source": "표 비고: 공항포장 지장물로 연속 포설 불가 시 시공량의 15%를 감한다",
            "cite": {"table_id": table}}],
    }
    finish(package, "daily_crew",
           "인원·장비 대수와 포장 종류별 일당 시공량이 표에 있고, 장비 목록·15% 감 규칙을 기존 일당 작업조 계산기가 처리한다.",
           [f"{table}에서 포장 종류에 따른 일당 시공량을 고른다.",
            "공항포장이며 지장물로 연속 포설이 불가능하면 시공량의 15%를 감한다.",
            "물량 ÷ 일당 시공량으로 작업일수를 구한다.",
            "작업일수 × 직종별 인원, × 장비 대수(콘크리트페이버·굴착기·살수차)로 총 투입량을 구한다."],
           params, source=f"{thickness_page} 표 및 [주]")


@promotion("토목/1-6-3")
def paving_small(package: dict) -> None:
    concrete_surface_paving(package, "p372-t0", "시공량", "PDF 316쪽 1-6-3")


@promotion("토목/1-6-4")
def paving_large(package: dict) -> None:
    concrete_surface_paving(package, "p372-t1", "시공량(㎥)", "PDF 316쪽 1-6-4")


def simple_crew_table(package: dict, *, table: str, output_row: str, output_column: str | dict,
                      crew: list[str], equipment: list[str], quantity_input: str, steps: list[str],
                      source: str, reason: str, extra: dict | None = None,
                      crew_column: dict | None = None) -> None:
    """인원·장비 수량 열과 시공량 행/열이 한 표에 있는 일당 작업조 절."""
    params = {
        "quantity_input": quantity_input,
        "base_output": {"table": table, "row": output_row, **output_column},
        "coefficients": [],
        "crew": {"table": table, **(crew_column or {"column": "수량"}), "trades": crew,
                 "rate_codes": {name: "" for name in crew}},
        "equipment": [{"name": name, "table": table, "column": "수량", "unit": "대·일"} for name in equipment],
        **(extra or {}),
    }
    finish(package, "daily_crew", reason, steps, params, source=source)


WATERING_REASON = ("순수 인력 살수 시 '살수품 100㎡당 1인 가산'의 직종과 살수차 제외 여부가 원문에 명시되지 않아 "
                   "계산하지 않고 보류한다(원문 비고).")


def road_base_laying(package: dict, *, table: str, crew: list[str], equipment: list[str], output_row: str) -> None:
    """도로 기층 포설: 일당 작업조 본 계산 + 원문이 정하지 않은 순수 인력 살수는 그대로 보류."""
    spec = package["draft"]
    spec["inputs"] = [item for item in spec["inputs"] if item["name"] not in ("area", "watering_area")]
    spec["blocked"] = [{**item, "reason": WATERING_REASON} for item in spec["blocked"]]
    simple_crew_table(
        package, table=table, output_row=output_row, output_column={"column": "시공량(㎥)"}, crew=crew,
        equipment=equipment, quantity_input="volume",
        steps=[f"{table}에서 일당 시공량을 고른다.", "물량 ÷ 일당 시공량으로 작업일수를 구한다.",
               "작업일수 × 직종별 인원, × 장비 대수로 총 투입량을 구한다.",
               "순수 인력 살수는 원문이 가산 직종·살수차 제외 여부를 정하지 않아 보류한다."],
        source=spec["quantity_model"].get("source") or "PDF 원문 표 및 비고",
        reason="일당 시공량·인원·장비 대수가 표에 있어 기존 일당 작업조 계산기로 표현된다. 다중 장비는 equipment 배열이 처리한다.")


@promotion("토목/1-3-2")
def road_1_3_2(package: dict) -> None:
    road_base_laying(package, table="p365-t0", crew=["포설공", "보통인부"],
                     equipment=["굴착기", "진동롤러", "살수차"], output_row="포설공")


@promotion("토목/1-4-2")
def road_1_4_2(package: dict) -> None:
    road_base_laying(package, table="p366-t0", crew=["포설공", "보통인부"],
                     equipment=["굴착기", "진동롤러", "살수차"], output_row="포설공")


@promotion("토목/1-4-3")
def road_1_4_3(package: dict) -> None:
    road_base_laying(package, table="p366-t1", crew=["포설공"],
                     equipment=["모터그레이더", "진동롤러", "살수차"], output_row="포설공")


@promotion("토목/1-5-3")
def asphalt_base_small(package: dict) -> None:
    spec = package["draft"]
    simple_crew_table(
        package, table="p367-t1", output_row="시공량(㎡)", output_column={"column_input": "thickness"},
        crew=["포장공", "보통인부"],
        equipment=["아스팔트피니셔", "굴착기", "머캐덤롤러", "타이어롤러", "탠덤롤러", "살수차"],
        quantity_input="area",
        steps=["p367-t1에서 1층 포설두께에 따른 일당 시공량을 고른다.", "시공 면적 ÷ 일당 시공량으로 작업일수를 구한다.",
               "작업일수 × 직종별 인원, × 장비 대수로 총 투입량을 구한다."],
        source="PDF 311쪽 1-5-3 표",
        reason="두께 열별 일당 시공량과 인원·장비 대수가 표에 있어 기존 일당 작업조 계산기로 표현된다.")


@promotion("공통/7-4-3")
def steel_truss_support(package: dict) -> None:
    """하지철물 설치와 석재판 붙임이 같은 물량(㎡)에 각자 일당 시공량을 갖는 두 작업."""
    simple_crew_table(
        package, table="p218-t1", output_row="용접공", output_column={"column_input": "panel_area"},
        crew=["용접공", "철공"], equipment=[], quantity_input="quantity",
        extra={"additional_work": [{
            "quantity_input": "quantity",
            "base_output": {"table": "p218-t1", "row": "석공", "column_input": "panel_area"},
            "crew_table": "p218-t1", "crew_column": "수량", "crew": ["석공", "줄눈공", "보통인부"],
            "source": "7-4-3 석재판 붙임: 하지철물 설치와 별도 시공량"}]},
        steps=["석재판 면적 구간으로 하지철물 설치(용접공·철공)의 일당 시공량을 고르고 작업일수를 구한다.",
               "같은 구간의 석재판 붙임(석공·줄눈공·보통인부) 일당 시공량으로 별도 작업일수를 구한다.",
               "각 작업일수 × 직종별 인원으로 인·일을 구하고 공구손료는 원문 비고의 3%를 비용 규칙으로 둔다."],
        source="PDF 162쪽 7-4-3 표 및 [주]",
        reason="두 작업이 각자 일당 시공량을 갖지만 같은 물량 기준이라 기존 additional_work(작업별 별도 시공량)로 표현된다.")


@promotion("공통/3-7-5")
def slope_reinforcement_drilling(package: dict) -> None:
    spec = package["draft"]
    table = next(t for t in spec["tables"] if t["id"] == "p137-t1")
    table["values"] = {
        "보링공": {"수량": "1"}, "특별인부": {"수량": "3"}, "보통인부": {"수량": "1"},
        "크롤러드릴(공기식)": {"수량": "1"}, "공기압축기": {"수량": "1"}, "크레인": {"수량": "1"}}
    equipment = [{"name": name, "table": "p137-t1", "column": "수량", "unit": "대·일"}
                 for name in ("크롤러드릴(공기식)", "공기압축기")]
    equipment.append({"name": "크레인", "table": "p137-t1", "column": "수량", "unit": "대·일",
                      "when": {"crane_excluded": False}})
    crew = ["보링공", "특별인부", "보통인부"]
    finish(package, "daily_crew",
           "인력·장비 편성 표(p137-t1)와 작업방식×지반 일당시공량 표(p137-t2)가 있어 기존 일당 작업조 계산기로 표현된다. "
           "크레인 제외는 원문 [주] ③의 현장 사실 입력으로 처리한다.",
           ["작업 방식과 지반 조건으로 p137-t2의 일당시공량(m)을 고른다.", "천공 길이 ÷ 일당시공량으로 작업일수를 구한다.",
            "작업일수 × 직종별 인원, × 장비 대수로 총 투입량을 구한다(크레인은 제외 조건이면 뺀다)."],
           {"quantity_input": "quantity",
            "base_output": {"table": "p137-t2", "row_input": "work_type", "column_input": "soil_type"},
            "coefficients": [],
            "crew": {"table": "p137-t1", "column": "수량", "trades": crew, "rate_codes": {n: "" for n in crew}},
            "equipment": equipment},
           source="PDF 3-7-5 2. 인력 및 장비 편성, 3. 일당시공량")


@promotion("유지관리/3-1-2")
def concrete_demolition_machine(package: dict) -> None:
    spec = package["draft"]
    crew = ["특별인부", "보통인부", "용접공"]
    finish(package, "daily_crew",
           "장애물 유무 열별 인원·장비 대수·일당 시공량이 한 표에 있고 재료량 표(p967-t2)는 materials로 표현된다.",
           ["장애물 제거 여부 열에서 일당 시공량을 고른다.", "물량 ÷ 일당 시공량으로 작업일수를 구한다.",
            "작업일수 × 직종별 인원, × 장비 대수(굴착기+압쇄기, 굴착기)로 총 투입량을 구한다.",
            "장애물 제거 시 산소·아세틸렌 재료량을 물량에 곱한다."],
           {"quantity_input": "volume",
            "base_output": {"table": "p967-t1", "row": "시공량(㎥)", "column_input": "obstacle_removal"},
            "coefficients": [],
            "crew": {"table": "p967-t1", "column_input": "obstacle_removal", "trades": crew,
                     "rate_codes": {n: "" for n in crew}},
            "equipment": [{"name": name, "table": "p967-t1", "column_input": "obstacle_removal", "unit": "대·일"}
                          for name in ("굴착기+압쇄기", "굴착기")],
            "materials": [
                {"when": {"obstacle_removal": "장애물 제거"}, "name": "산소(대기압상태기준)", "table": "p967-t2",
                 "row": "산소(대기압상태기준)", "unit": "L"},
                {"when": {"obstacle_removal": "장애물 제거"}, "name": "아세틸렌", "table": "p967-t2",
                 "row": "아세틸렌", "unit": "㎏"}]},
           source="PDF 911쪽 3-1-2 표 및 [주] ⑧")


@promotion("유지관리/2-1-33")
def curb_reinstall(package: dict) -> None:
    crew = ["특별인부", "보통인부"]
    row = {"input": "type_class", "contains": ["{value}", "{trade}"]}
    finish(package, "daily_crew",
           "Type별 인원·장비와 규격×구간별 일당 시공량이 표에 있어 복합 행 선택자로 표현된다.",
           ["Type·규격·구간(직선/곡선)으로 일당 시공량(m)을 고른다.", "물량 ÷ 일당 시공량으로 작업일수를 구한다.",
            "Type별 직종 인원·장비 대수(굴착기·트럭)를 작업일수에 곱한다.",
            "공구손료·경장비는 인력품의 2%를 비용 규칙으로 둔다."],
           {"quantity_input": "quantity",
            "base_output": {"table": "p948-t2",
                            "row_selector": {"input": "type_class", "contains": ["{value}"],
                                             "exact_input_contains": ["size"]},
                            "column_input": "section_type"},
            "coefficients": [],
            "crew": {"table": "p948-t2", "column": "수량", "trades": crew, "row_selector": row,
                     "rate_codes": {n: "" for n in crew}},
            "equipment": [
                {"name": "굴착기 0.4㎥", "table": "p948-t2", "row": "A-Type_굴착기_0.4㎥", "column": "수량",
                 "unit": "대·일", "when": {"type_class": "A-Type"}},
                {"name": "굴착기 0.2㎥", "table": "p948-t2", "row": "B-Type_굴착기_0.2㎥", "column": "수량",
                 "unit": "대·일", "when": {"type_class": "B-Type"}},
                {"name": "트럭 2.5ton", "table": "p948-t2", "row": "A-Type_트럭_2.5ton", "column": "수량",
                 "unit": "대·일", "when": {"type_class": "A-Type"}},
                {"name": "트럭 2.5ton", "table": "p948-t2", "row": "B-Type_트럭_2.5ton", "column": "수량",
                 "unit": "대·일", "when": {"type_class": "B-Type"}}]},
           source="PDF 892쪽 2-1-33 표 및 [주]")


@promotion("토목/1-8-1")
def traffic_sign_install(package: dict) -> None:
    crew = ["특별인부", "보통인부"]
    finish(package, "daily_crew",
           "지주/표지판 행별 인원·크레인·일당 시공량이 표에 있어 기존 일당 작업조 계산기로 표현된다.",
           ["설치 대상(지주/표지판) 행의 일당 시공량(개소)을 고른다.", "물량 ÷ 일당 시공량으로 작업일수를 구한다.",
            "작업일수 × 직종별 인원을 구하고 지주는 크레인 1대를 곱한다."],
           {"quantity_input": "quantity",
            "base_output": {"table": "p376-t1", "row_input": "work_type", "column": "시공량"},
            "coefficients": [],
            "crew": {"table": "p376-t1", "row_input": "work_type", "column_template": "{trade}", "trades": crew,
                     "rate_codes": {n: "" for n in crew}},
            "equipment": [{"name": "크레인", "table": "p376-t1", "row_selector": "work_type", "column": "크레인",
                           "unit": "대·일", "when": {"work_type": "지주"}}]},
           source="PDF 320쪽 1-8-1 표 및 [주]")


@promotion("공통/6-7-3")
def pc_box_install(package: dict) -> None:
    spec = package["draft"]
    weights = field(spec, "unit_weight")["allowed_values"]
    envs = field(spec, "work_env")["allowed_values"]
    source_rows = [("20", "15"), ("16", "12"), ("14", "11")]
    table = next(t for t in spec["tables"] if t["id"] == "p212-t1")
    # 원문은 인원·장비 목록과 (단위중량 × Type) 시공량 표가 나란히 놓인 구조다. 두 부분을 행으로 분리해 옮긴다.
    table["values"] = {
        "기계설비공": {"수량": "2"}, "특별인부": {"수량": "4"}, "보통인부": {"수량": "2"},
        "크레인": {"수량": "1"}, "강연선인장기": {"수량": "1"},
        **{weight: {env: value for env, value in zip(envs, row)} for weight, row in zip(weights, source_rows)}}
    crew = ["기계설비공", "특별인부", "보통인부"]
    finish(package, "daily_crew",
           "인원·장비 대수와 (단위중량 × 작업환경 Type) 일당 시공량이 표에 있어 기존 일당 작업조 계산기로 표현된다.",
           ["단위중량 행과 작업환경 Type 열로 일당 시공량(개소)을 고른다.", "설치 개소 ÷ 일당 시공량으로 작업일수를 구한다.",
            "작업일수 × 직종별 인원, × 장비 대수(크레인·강연선인장기)로 총 투입량을 구한다."],
           {"quantity_input": "quantity",
            "base_output": {"table": "p212-t1", "row_input": "unit_weight", "column_input": "work_env"},
            "coefficients": [],
            "crew": {"table": "p212-t1", "column": "수량", "trades": crew, "rate_codes": {n: "" for n in crew}},
            "equipment": [{"name": name, "table": "p212-t1", "column": "수량", "unit": "대·일"}
                          for name in ("크레인", "강연선인장기")]},
           source="PDF 156쪽 6-7-3 표 및 [주]")


@promotion("공통/6-6-2")
def bridge_bearing_water(package: dict) -> None:
    spec = package["draft"]
    heights = field(spec, "height")["allowed_values"]
    # 원문은 중량 블록마다 (특별인부 n, 보통인부 1, 용접공 1, 크레인 1, 고소작업차 1)와 높이별 시공량이 반복된다.
    blocks = {"0.2ton이하": (2, ("5.0", "4.0", "3.5")), "0.3ton이하": (2, ("3.5", "3.0", "2.5")),
              "0.5ton이하": (3, ("3.0", "2.5", "2.0")), "1.0ton이하": (3, ("2.5", "2.0", "1.7")),
              "1.5ton이하": (4, ("2.3", "1.8", "1.5")), "1.5ton초과": (4, ("2.0", "1.5", "1.3"))}
    table = next(t for t in spec["tables"] if t["id"] == "p208-t0")
    table["values"] = {
        weight: {"특별인부": str(special), "보통인부": "1", "용접공": "1", "크레인": "1", "고소작업차": "1",
                 **dict(zip(heights, outputs))}
        for weight, (special, outputs) in blocks.items()}
    crew = ["특별인부", "보통인부", "용접공"]
    finish(package, "daily_crew",
           "교량받침 중량 블록별 인원·장비 대수와 설치높이별 일당 시공량이 반복되는 정규 구조라 기존 일당 작업조 계산기로 표현된다.",
           ["중량 블록과 설치높이로 일당 시공량(개)을 고른다.", "설치 수량 ÷ 일당 시공량으로 작업일수를 구한다.",
            "작업일수 × 해당 중량 블록의 직종별 인원, × 장비 대수(크레인·고소작업차)로 총 투입량을 구한다."],
           {"quantity_input": "quantity",
            "base_output": {"table": "p208-t0", "row_input": "weight", "column_input": "height"},
            "coefficients": [],
            "crew": {"table": "p208-t0", "row_input": "weight", "column_template": "{trade}", "trades": crew,
                     "rate_codes": {n: "" for n in crew}},
            "equipment": [{"name": name, "table": "p208-t0", "row_selector": "weight", "column": name, "unit": "대·일"}
                          for name in ("크레인", "고소작업차")]},
           source="PDF 152쪽 6-6-2 표 및 [주]")


@promotion("유지관리/1-1-2")
def bearing_plate_block(package: dict) -> None:
    # 고소작업차 제외 조건은 앞 절(1-1-1) [주]이지 1-1-2의 것이 아니다. 이전 시도에서 넣은 입력을 제거한다.
    package["draft"]["inputs"] = [i for i in package["draft"]["inputs"] if i["name"] != "workers_on_ground"]
    crew = ["중급기술자", "보링공", "특별인부", "보통인부"]
    finish(package, "daily_crew",
           "인원·장비 대수와 일당 시공량(개소)이 한 표에 있어 기존 일당 작업조 계산기로 표현된다.",
           ["일당 시공량 9개소로 설치 개소 ÷ 9 = 작업일수를 구한다.",
            "작업일수 × 직종별 인원, × 장비 대수(크레인·고소작업차·강연선인장기)로 총 투입량을 구한다.",
            "블록 2ton 초과·비탈경사/수직고 기준 초과는 원문 범위 밖이라 보류한다."],
           {"quantity_input": "quantity",
            "base_output": {"table": "p914-t0", "row": "시공량", "column": "개소"},
            "coefficients": [],
            "crew": {"table": "p914-t0", "column": "수량", "trades": crew, "rate_codes": {n: "" for n in crew}},
            "equipment": [{"name": name, "table": "p914-t0", "column": "수량", "unit": "대·일"}
                          for name in ("크레인", "고소작업차", "강연선인장기")]},
           source="PDF 858쪽 1-1-2 표 및 [주]")


def guardrail_like(package: dict, *, post_table: str, plate_table: str, post_values: dict, plate_values: dict,
                   post_equipment: list[str], plate_equipment: list[str]) -> None:
    """가드레일/중앙분리대(가드레일식): 지주 설치·판 설치 두 표 중 하나를 work_type으로 고른다."""
    spec = package["draft"]
    tables = {t["id"]: t for t in spec["tables"]}
    tables[post_table]["values"] = post_values
    tables[plate_table]["values"] = plate_values
    plate_only = {"input": "work_type", "equals": "판 설치"}
    plate = field(spec, "plate_type")
    upsert_input(spec, {**plate, "allowed_values": ["2W", "3W"], "when": plate_only})
    if any(item["name"] == "is_curve" for item in spec["inputs"]):
        upsert_input(spec, {**field(spec, "is_curve"), "when": plate_only})
    route = {"input": "work_type", "values": {"지주 설치": post_table, "판 설치": plate_table}}
    equipment = [{"name": name, "table": post_table, "column": "수량", "unit": "대·일",
                  "when": {"work_type": "지주 설치"}} for name in post_equipment]
    equipment += [{"name": name, "table": plate_table, "column": "수량", "unit": "대·일",
                   "when": {"work_type": "판 설치"}} for name in plate_equipment]
    crew = ["특별인부", "보통인부"]
    finish(package, "daily_crew",
           "지주 설치/판 설치 두 표를 작업 종류로 골라 일당 시공량·인원·장비 대수를 읽는 일당 작업조 구조다.",
           ["작업 종류로 지주 설치표 또는 판 설치표를 고른다.", "지주간격(및 판 설치는 2W/3W)으로 일당 시공량(m)을 고른다.",
            "설치 물량 ÷ 일당 시공량으로 작업일수를 구한다.", "작업일수 × 직종별 인원, × 장비 대수로 총 투입량을 구한다."],
           {"quantity_input": "quantity",
            "base_output": {"table_selector": route, "row": "특별인부",
                            "column_selector": {"input": "post_spacing", "contains": ["지주간격{value}"],
                                                "optional_input_contains": ["plate_type"]}},
            "coefficients": [],
            "crew": {"table_selector": route, "column": "수량", "trades": crew,
                     "rate_codes": {n: "" for n in crew}},
            "equipment": equipment},
           source="PDF 원문 1. 지주 설치 / 2. 판 설치 표")


@promotion("토목/1-8-10")
def guardrail(package: dict) -> None:
    guardrail_like(
        package, post_table="p381-t0", plate_table="p381-t1",
        post_values={"특별인부": {"수량": "2", "지주간격 2m": "420", "지주간격 4m": "840"},
                     "보통인부": {"수량": "1", "지주간격 2m": "420", "지주간격 4m": "840"},
                     "굴착기+대형브레이커": {"수량": "1"}, "트럭": {"수량": "1"}},
        plate_values={name: {"수량": count, "지주간격 2m 2W": "520", "지주간격 2m 3W": "440",
                             "지주간격 4m 2W": "680", "지주간격 4m 3W": "560"}
                      for name, count in (("특별인부", "4"), ("보통인부", "2"))} | {"트럭": {"수량": "1"}},
        post_equipment=["굴착기+대형브레이커", "트럭"], plate_equipment=["트럭"])


@promotion("토목/1-8-11")
def median_guardrail(package: dict) -> None:
    guardrail_like(
        package, post_table="p381-t2", plate_table="p382-t0",
        post_values={"특별인부": {"수량": "3", "지주간격 2m": "260", "지주간격 4m": "520"},
                     "보통인부": {"수량": "1", "지주간격 2m": "260", "지주간격 4m": "520"},
                     "굴착기+대형브레이커": {"수량": "1"}, "크롤러드릴(공기식)": {"수량": "1"},
                     "공기압축기": {"수량": "1"}, "트럭": {"수량": "1"}},
        plate_values={name: {"수량": count, "지주간격 2m 2W": "260", "지주간격 2m 3W": "220",
                             "지주간격 4m 2W": "340", "지주간격 4m 3W": "280"}
                      for name, count in (("특별인부", "4"), ("보통인부", "2"))} | {"트럭": {"수량": "1"}},
        post_equipment=["굴착기+대형브레이커", "크롤러드릴(공기식)", "공기압축기", "트럭"], plate_equipment=["트럭"])


@promotion("토목/6-3-1")
def steel_pipe_laying(package: dict) -> None:
    # 기존 인용문이 청크의 줄바꿈 표지(설명 |)를 가로질러 검증에 실패했다. 한 줄에 있는 앞부분만 인용한다.
    whole = ("③ 양중장비의 규격은 작업여건(시공높이, 시공위치 등) 및 안전율(적정하중, 작업반경 등)을 고려하여 적합한 규격을 적용한다.")
    first_line = "③ 양중장비의 규격은 작업여건(시공높이, 시공위치 등) 및 안전율(적정하중, 작업반경 등)을 고려하여"
    for item in package["citations"] + [n["cite"] for n in package["draft"]["not_calculated"]]:
        if item.get("quote") == whole:
            item["quote"] = first_line
    spec = package["draft"]
    tables = {t["id"]: t for t in spec["tables"]}
    # 장비 부설표와 인력 부설표의 관경 행이 다르므로(인력은 80~250) 방법별로 해당 관경만 묻는다.
    base = field(spec, "pipe_diameter")
    upsert_input(spec, {**base, "allowed_values": list(tables["p422-t0"]["values"]),
                        "when": {"input": "installation_method", "equals": "장비 부설"}})
    upsert_input(spec, {**base, "name": "manual_pipe_diameter", "allowed_values": list(tables["p422-t1"]["values"]),
                        "when": {"input": "installation_method", "equals": "인력 부설"},
                        "source": "PDF 366쪽 6-3-1 비고(인력 부설) 표"})
    diameter = ["pipe_diameter", "manual_pipe_diameter"]
    crew = ["배관공(수도)", "보통인부"]
    route = {"input": "installation_method", "values": {"장비 부설": "p422-t0", "인력 부설": "p422-t1"}}
    finish(package, "daily_crew",
           "부설 방법별 표(장비/인력)에서 관경 행의 인원·양중장비·일당 시공량(본)을 읽는 일당 작업조 구조다.",
           ["부설 방법으로 장비 부설표(p422-t0) 또는 인력 부설표(p422-t1)를 고른다.",
            "관경 행의 일당 시공량(본)을 읽고 물량 ÷ 시공량으로 작업일수를 구한다.",
            "작업일수 × 직종별 인원, 장비 부설이면 × 양중장비 대수로 총 투입량을 구한다."],
           {"quantity_input": "quantity",
            "base_output": {"table_selector": route, "row_input": diameter, "column": "시공량(본)"},
            "coefficients": [],
            "crew": {"table_selector": route, "row_input": diameter, "column_template": "{trade}",
                     "trades": crew, "rate_codes": {n: "" for n in crew}},
            "equipment": [{"name": "양중장비", "table": "p422-t0", "row_selector": "pipe_diameter",
                           "column": "양중장비", "unit": "대·일", "when": {"installation_method": "장비 부설"}}]},
           source="PDF 366쪽 6-3-1 표 및 비고(인력 부설)")


@promotion("토목/1-9-2")
def curb_install(package: dict) -> None:
    crew = ["특별인부", "보통인부"]
    finish(package, "daily_crew",
           "Type별 인원·굴착기 대수와 규격×(Type, 선형)별 일당 시공량이 표에 있어 기존 일당 작업조 계산기로 표현된다.",
           ["Type, 경계블록 규격, 직선/곡선 구간으로 일당 시공량(m)을 고른다.", "설치 물량 ÷ 일당 시공량으로 작업일수를 구한다.",
            "Type별 직종 인원·굴착기 대수를 작업일수에 곱한다."],
           {"quantity_input": "quantity",
            "base_output": {"table": "p385-t0", "row_input": "block_size",
                            "column_selector": {"input": "block_type", "contains": ["{value}"],
                                                "input_contains": ["alignment"]}},
            "coefficients": [],
            "crew": {"table": "p385-t0", "column_input": "block_type", "trades": crew,
                     "rate_codes": {n: "" for n in crew}},
            "equipment": [
                {"name": "굴착기(0.4㎥)", "table": "p385-t0", "column": "A-Type", "unit": "대·일",
                 "when": {"block_type": "A-Type"}},
                {"name": "굴착기(0.2㎥)", "table": "p385-t0", "column": "B-Type", "unit": "대·일",
                 "when": {"block_type": "B-Type"}}]},
           source="PDF 329쪽 1-9-2 표 및 [주]")


_CHUNKS: list[dict] | None = None


def chunk_for(section_no: str, needle: str, division: str | None = None) -> str:
    """section_no 청크 중 needle을 (공백 무시) 포함하는 것의 chunk_id. 정확히 하나여야 한다."""
    global _CHUNKS
    if _CHUNKS is None:
        _CHUNKS = [json.loads(l) for l in CHUNKS.read_text(encoding="utf-8").splitlines() if l.strip()]
    squash = lambda text: "".join(text.split()).replace(",", "")
    hits = [c["chunk_id"] for c in _CHUNKS
            if squash(needle) in squash(c.get("text", "")) and c.get("section_no") == section_no
            and (division is None or c.get("division") == division)]
    if len(hits) != 1:
        raise LookupError(f"{section_no}: '{needle[:20]}' 청크 {hits}")
    return hits[0]


BLOCK_COST_NEEDLE = "공구손료 및 경장비(절단기 등)의 기계경비는 인력품의 5%, 블록 정밀절단(전동절단기)에 의한"


def sidewalk_block(package: dict, *, table: str, section: str, outputs: dict, crew: dict, equipment: dict,
                   quantity: str, type_input: str, tactile: tuple[str, object], precision: str,
                   source: str) -> None:
    """보도 블록 설치/재설치: Type(A/B)별 인원·장비·시공량, 유도블록 10% 감, 정밀절단 아님 특별인부 1인 감,
    공구손료 5%(정밀절단)/2%(아님). 원문 '-'는 해당 Type에 그 장비가 없다는 뜻이라 0을 채우지 않는다."""
    spec = package["draft"]
    types = field(spec, type_input)["allowed_values"]
    values = {trade: dict(zip(types, counts)) for trade, counts in crew.items()}
    values.update({name: {t: c for t, c in zip(types, counts) if c is not None} for name, counts in equipment.items()})
    values["시공량"] = dict(zip(types, outputs))
    next(t for t in spec["tables"] if t["id"] == table)["values"] = values
    chunk = chunk_for(section, BLOCK_COST_NEEDLE)
    quote = BLOCK_COST_NEEDLE
    spec["cost_rules"] = [
        {"name": "공구손료 및 경장비(정밀절단 시공)", "category": "경비", "base": "labor_subtotal", "rate": "0.05",
         "when": {precision: True}, "cite": {"chunk_id": chunk, "quote": quote}},
        {"name": "공구손료 및 경장비(정밀절단 아님)", "category": "경비", "base": "labor_subtotal", "rate": "0.02",
         "when": {precision: False}, "cite": {"chunk_id": chunk, "quote": quote}}]
    spec["crew_rules"] = [{"when": {precision: False}, "when_text": "블록 정밀절단(전동절단기)에 의한 시공이 아닌 경우",
                           "change": {"특별인부": "-1"}, "source": "표 비고", "cite": {"table_id": table}}]
    spec["blocked"] = []
    equipment_items = []
    for name, counts in equipment.items():
        for kind, count in zip(types, counts):
            if count is not None:
                equipment_items.append({"name": name, "table": table, "column": kind, "unit": "대·일",
                                        "when": {type_input: kind}})
    trades = list(crew)
    finish(package, "daily_crew",
           "Type별 인원·장비·일당 시공량이 표에 있고 비고의 시공량 10% 감·특별인부 1인 감·조건부 경비율을 기존 필드와 "
           "조건부 비용 규칙(cost_rules.when)으로 표현한다. 원문 '-'(해당 Type에 없는 장비)는 0으로 바꾸지 않는다.",
           ["Type 열의 일당 시공량을 고른다.", "유도·점자블록이면 시공량의 10%를 감한다.",
            "정밀절단이 아니면 특별인부 1인을 감한다.", "물량 ÷ 일당 시공량으로 작업일수를 구하고 인원·장비 대수를 곱한다.",
            "공구손료·경장비는 인력품의 5%(정밀절단) 또는 2%(정밀절단 아님)."],
           {"quantity_input": quantity,
            "base_output": {"table": table, "row": "시공량", "column_input": type_input},
            "coefficients": [],
            "crew": {"table": table, "column_input": type_input, "trades": trades,
                     "rate_codes": {n: "" for n in trades}},
            "equipment": equipment_items,
            "output_adjustments": [{
                "when": {tactile[0]: tactile[1]}, "operation": "set_output_percent", "value": "10",
                "source": "표 비고: 유도·점자블록을 설치하는 경우 시공량의 10%를 감하여 적용한다",
                "cite": {"table_id": table}}]},
           source=source)


@promotion("토목/1-7-1")
def block_small(package: dict) -> None:
    sidewalk_block(package, table="p374-t0", section="1-7-1", outputs=("300", "190"),
                   crew={"포장공": ("3", "2"), "특별인부": ("2", "2"), "보통인부": ("2", "1")},
                   equipment={"굴착기 0.6㎥": ("1", None), "굴착기 0.4㎥": (None, "1"), "플레이트콤팩터 1.5ton": ("1", "1")},
                   quantity="volume", type_input="site_condition", tactile=("block_type", "유도･점자블록"),
                   precision="cutting_method", source="PDF 318쪽 1-7-1 표 및 [주]")


@promotion("토목/1-7-2")
def block_large(package: dict) -> None:
    sidewalk_block(package, table="p374-t2", section="1-7-2", outputs=("190", "120"),
                   crew={"포장공": ("3", "2"), "특별인부": ("2", "2"), "보통인부": ("2", "1")},
                   equipment={"굴착기 0.6㎥": ("1", None), "굴착기 0.4㎥": (None, "1"), "플레이트콤팩터 1.5ton": ("1", "1")},
                   quantity="volume", type_input="site_condition", tactile=("block_type", True),
                   precision="precision_cut", source="PDF 319쪽 1-7-2 표 및 [주]")


@promotion("유지관리/2-1-29")
def block_reinstall_small(package: dict) -> None:
    sidewalk_block(package, table="p946-t0", section="2-1-29", outputs=("260", "180"),
                   crew={"포장공": ("3", "2"), "특별인부": ("2", "2"), "보통인부": ("2", "1")},
                   equipment={"굴착기 0.4㎥": ("1", None), "굴착기 0.2㎥": (None, "1"),
                              "플레이트콤팩터 1.5ton": ("1", "1"), "트럭 2.5ton": ("1", "1")},
                   quantity="area", type_input="site_type", tactile=("tactile_block", True),
                   precision="precision_cut", source="PDF 890쪽 2-1-29 표 및 [주]")


@promotion("유지관리/2-1-30")
def block_reinstall_large(package: dict) -> None:
    sidewalk_block(package, table="p946-t2", section="2-1-30", outputs=("160", "100"),
                   crew={"포장공": ("3", "2"), "특별인부": ("2", "2"), "보통인부": ("2", "1")},
                   equipment={"굴착기 0.4㎥": ("1", None), "굴착기 0.2㎥": (None, "1"),
                              "플레이트콤팩터 1.5ton": ("1", "1"), "트럭 2.5ton": ("1", "1")},
                   quantity="volume", type_input="type", tactile=("tactile_block", True),
                   precision="precision_cut", source="PDF 890쪽 2-1-30 표 및 [주]")


@promotion("토목/1-9-3")
def rockfall_fence(package: dict) -> None:
    spec = package["draft"]
    tables = {t["id"]: t for t in spec["tables"]}
    tables["p385-t2"]["values"] = {"용접공": {"수량": "1"}, "특별인부": {"수량": "3"}, "보통인부": {"수량": "2"},
                                   "크레인": {"수량": "1"}, "시공량": {"수량": "40"}}
    tables["p386-t0"]["values"] = {"특별인부": {"수량": "4"}, "보통인부": {"수량": "2"}, "시공량": {"수량": "200"}}
    tables["p386-t1"]["values"] = {"특별인부": {"수량": "4"}, "보통인부": {"수량": "2"}, "시공량": {"수량": "360"}}
    scaffold = next(i for i in spec["inputs"] if i["name"] in ("scaffold_needed", "scaffold_wire"))
    spec["inputs"] = [i for i in spec["inputs"] if not i["name"].startswith("scaffold_")]
    scaffold_cite = {"와이어 설치": {"chunk_id": "p386-x3", "quote": "③ 비계가 필요한 경우 별도 계상한다."},
                     "철망 설치": {"chunk_id": "p386-x8", "quote": "③ 비계가 필요한 경우 별도 계상한다."}}
    for name, work in (("scaffold_wire", "와이어 설치"), ("scaffold_mesh", "철망 설치")):
        upsert_input(spec, {**scaffold, "name": name, "when": {"input": "work_type", "equals": work},
                            "ask": f"{work} 작업에 비계가 필요합니까?"})
    spec["blocked"] = [
        {"condition": f"{work}에 비계가 필요한 경우", "blocked_if": {"input": name, "op": "==", "value": True},
         "reason": "비계가 필요한 경우 별도 계상한다(원문 [주] ③).", "source": f"PDF 330쪽 {work} [주] ③",
         "cite": scaffold_cite[work]}
        for name, work in (("scaffold_wire", "와이어 설치"), ("scaffold_mesh", "철망 설치"))]
    cutter = "④ 공구손료 및 경장비(절단기 등)의 기계경비는 인력품의 2%로 계상한다."
    spec["cost_rules"] = [
        {"name": "공구손료 및 경장비(용접기 등)", "category": "경비", "base": "labor_subtotal", "rate": "0.02",
         "when": {"work_type": "지주 설치"}, "cite": {"chunk_id": "p385-x26",
          "quote": "④ 공구손료 및 경장비(용접기 등)의 기계경비는 인력품의 2%로 계상한다."}},
        {"name": "공구손료 및 경장비(절단기 등)", "category": "경비", "base": "labor_subtotal", "rate": "0.02",
         "when": {"work_type": "와이어 설치"}, "cite": {"chunk_id": "p386-x3", "quote": cutter}},
        {"name": "공구손료 및 경장비(절단기 등)", "category": "경비", "base": "labor_subtotal", "rate": "0.02",
         "when": {"work_type": "철망 설치"}, "cite": {"chunk_id": "p386-x8", "quote": cutter}}]
    route = {"input": "work_type", "values": {"지주 설치": "p385-t2", "와이어 설치": "p386-t0", "철망 설치": "p386-t1"}}
    trades = {"지주 설치": ["용접공", "특별인부", "보통인부"], "와이어 설치": ["특별인부", "보통인부"],
              "철망 설치": ["특별인부", "보통인부"]}
    finish(package, "daily_crew",
           "작업 종류(지주/와이어/철망)별 표에서 인원·일당 시공량을 읽는 일당 작업조 구조이며 지주만 크레인이 있다.",
           ["작업 종류로 해당 표를 고른다.", "물량(지주 개, 와이어 m, 철망 ㎡) ÷ 일당 시공량으로 작업일수를 구한다.",
            "작업일수 × 직종별 인원, 지주는 × 크레인 1대로 총 투입량을 구한다.",
            "비계가 필요한 와이어·철망 설치는 원문이 별도 계상하라고 하여 보류한다."],
           {"quantity_input": "quantity",
            "base_output": {"table_selector": route, "row": "시공량", "column": "수량"},
            "coefficients": [],
            "crew": {"table_selector": route, "column": "수량", "trade_selector_input": "work_type",
                     "trades_by_input": trades, "rate_codes": {n: "" for t in trades.values() for n in t}},
            "equipment": [{"name": "크레인", "table": "p385-t2", "column": "수량", "unit": "대·일",
                           "when": {"work_type": "지주 설치"}}]},
           source="PDF 329~330쪽 1-9-3 표 및 [주]")
    for table_id in tables:
        refresh_table_citations(package, table_id)
    # 작업 종류마다 물량 단위가 다르다(지주 개, 와이어 m, 철망 ㎡): 공통 규칙 `unit_by`로 선언한다.
    upsert_input(spec, {**field(spec, "quantity"), "unit_by": {"input": "work_type", "values": {
        "지주 설치": "개", "와이어 설치": "m", "철망 설치": "㎡"}}})


@promotion("토목/4-3-3")
def track_cleanup(package: dict) -> None:
    spec = package["draft"]
    table = next(t for t in spec["tables"] if t["id"] == "p403-t1")
    table["values"] = {"궤도공": {"수량": "9"}, "보통인부": {"수량": "6"}, "측량중급기술자": {"수량": "1"},
                       "양로기": {"수량": "1"}, "시공량": {"수량": "250"}}
    spec["blocked"] = [{
        "condition": "단선궤도", "blocked_if": {"input": "track_type", "op": "==", "value": "단선"},
        "reason": "원문은 단선궤도의 시공량을 '5%까지' 감한다고만 하여 적용 감산율이 정해져 있지 않다(본 품은 복선 기준).",
        "source": "PDF 4-3-3 표 비고", "cite": {"table_id": "p403-t1"}}]
    crew = ["궤도공", "보통인부", "측량중급기술자"]
    finish(package, "daily_crew",
           "복선 기준 인원·양로기·일당 시공량이 표에 있어 일당 작업조 계산기로 표현된다. 단선의 감산율은 원문이 범위만 정해 보류한다.",
           ["일당 시공량 250m로 구간 길이 ÷ 250 = 작업일수를 구한다.",
            "작업일수 × 직종별 인원, × 양로기 1대로 총 투입량을 구한다.",
            "단선궤도는 원문이 감산율을 '5%까지'로만 정해 계산하지 않는다."],
           {"quantity_input": "length",
            "base_output": {"table": "p403-t1", "row": "시공량", "column": "수량"},
            "coefficients": [],
            "crew": {"table": "p403-t1", "column": "수량", "trades": crew, "rate_codes": {n: "" for n in crew}},
            "equipment": [{"name": "양로기", "table": "p403-t1", "column": "수량", "unit": "대·일"}]},
           source="PDF 4-3-3 표 및 비고")
    refresh_table_citations(package, "p403-t1")


@promotion("유지관리/2-1-27")
def block_manual_removal(package: dict) -> None:
    spec = package["draft"]
    types = field(spec, "site_type")["allowed_values"]
    values = {"포장공": ("2", "2"), "보통인부": ("2", "1"), "트럭 2.5ton": ("1", "1"), "시공량": ("360", "260")}
    table = {"id": "p945-t0", "role": "Type별 인원·장비 대수와 일당 시공량", "source": "PDF 2-1-27 표", "unit": "인, 대, ㎡/일",
             "values": {name: dict(zip(types, counts)) for name, counts in values.items()},
             "cite": {"table_id": "p945-t0"}}
    spec["tables"] = [t for t in spec["tables"] if t["id"] != "p945-t0"] + [table]
    spec["blocked"] = []
    crew = ["포장공", "보통인부"]
    finish(package, "daily_crew",
           "Type별 인원·트럭 대수와 일당 시공량이 표에 있어 기존 일당 작업조 계산기로 표현된다.",
           ["Type 열의 일당 시공량(㎡)을 고른다.", "철거 면적 ÷ 일당 시공량으로 작업일수를 구한다.",
            "작업일수 × 직종별 인원, × 트럭 1대로 총 투입량을 구한다."],
           {"quantity_input": "area",
            "base_output": {"table": "p945-t0", "row": "시공량", "column_input": "site_type"},
            "coefficients": [],
            "crew": {"table": "p945-t0", "column_input": "site_type", "trades": crew,
                     "rate_codes": {n: "" for n in crew}},
            "equipment": [{"name": "트럭 2.5ton", "table": "p945-t0", "column_input": "site_type", "unit": "대·일"}]},
           source="PDF 890쪽 2-1-27 표 및 [주]")
    refresh_table_citations(package, "p945-t0")


@promotion("토목/1-9-4")
def rockfall_net(package: dict) -> None:
    spec = package["draft"]
    tables = {t["id"]: t for t in spec["tables"]}
    tables["p386-t2"]["values"] = {
        "착암공": {"수량": "2"}, "비계공": {"수량": "3"}, "보통인부": {"수량": "2"},
        "공기압축기": {"수량": "1"}, "소형브레이커": {"수량": "2"}, "시공량": {"수량": "800"}}
    tables["p387-t0"]["values"] = {
        "특별인부": {"기계식": "2", "인력식": "2"}, "보통인부": {"기계식": "3", "인력식": "3"},
        "크레인": {"기계식": "1"}, "시공량": {"기계식": "400", "인력식": "100"}}
    upsert_input(spec, {"name": "foundation_drilling", "type": "boolean", "allowed_values": [True, False],
                        "unit": None, "required": True, "ask": "낙석방지망 설치를 위한 기초천공(착암) 작업이 포함됩니까?",
                        "source": "PDF 1-9-4 1. 기초 착암"})
    foundation = ["착암공", "비계공", "보통인부"]
    finish(package, "daily_crew",
           "철망·와이어 설치(방식별 시공량)와 기초 착암(별도 시공량)은 같은 면적에 각자 시공량을 갖는 두 작업이라 "
           "additional_work로 표현한다. 재료량은 [참고자료]의 ㎡당 수량이다.",
           ["설치 방식(기계식/인력식)의 일당 시공량으로 철망·와이어 설치 작업일수를 구한다.",
            "기초천공이 포함되면 기초 착암(800㎡/일)의 작업일수를 따로 구해 인력·장비를 더한다.",
            "재료량은 ㎡당 철망 1.15㎡, 결속선 0.3m, 에폭시 0.01kg(포켓식만)이다."],
           {"quantity_input": "volume",
            "base_output": {"table": "p387-t0", "row": "시공량", "column_input": "installation_method"},
            "coefficients": [],
            "crew": {"table": "p387-t0", "column_input": "installation_method", "trades": ["특별인부", "보통인부"],
                     "rate_codes": {"특별인부": "", "보통인부": ""}},
            "equipment": [{"name": "크레인", "table": "p387-t0", "column": "기계식", "unit": "대·일",
                           "when": {"installation_method": "기계식"}}],
            "additional_work": [{
                "when": {"foundation_drilling": True}, "quantity_input": "volume",
                "base_output": {"table": "p386-t2", "row": "시공량", "column": "수량"},
                "crew_table": "p386-t2", "crew_column": "수량", "crew": foundation,
                "equipment": [{"name": name, "table": "p386-t2", "row": name, "column": "수량", "unit": "대·일"}
                              for name in ("공기압축기", "소형브레이커")],
                "source": "1-9-4 1. 기초 착암(별도 시공량 800㎡/일)"}],
            "materials": [
                {"name": "철망", "table": "p387-t1", "row": "철망", "unit": "㎡"},
                {"name": "결속선", "table": "p387-t1", "row": "결속선", "unit": "m"},
                {"name": "에폭시", "table": "p387-t1", "row": "에폭시", "unit": "kg", "when": {"net_type": "포켓식"}}]},
           source="PDF 330~331쪽 1-9-4 표 및 [참고자료]")
    for table_id in ("p386-t2", "p387-t0"):
        refresh_table_citations(package, table_id)


def retype(package: dict, table_id: str, values: dict) -> None:
    """PDF 원문에서 옮긴 값으로 표를 교체하고 패키지 인용을 다시 만든다(옮긴 값은 검사 스크립트가 PDF와 대조)."""
    next(t for t in package["draft"]["tables"] if t["id"] == table_id)["values"] = values
    refresh_table_citations(package, table_id)


GENERIC_REASON = "인원·장비 대수와 일당 시공량이 표에 있어 기존 일당 작업조 계산기로 표현된다."
GENERIC_STEPS = ["표에서 일당 시공량을 고른다.", "물량 ÷ 일당 시공량으로 작업일수를 구한다.",
                 "작업일수 × 직종별 인원, × 장비 대수로 총 투입량을 구한다."]


@promotion("유지관리/2-1-21")
def sign_removal(package: dict) -> None:
    retype(package, "p943-t1", {"특별인부": {"수량": "2"}, "보통인부": {"수량": "1"}, "트럭": {"수량": "1"},
                                "시공량": {"수량": "17"}})
    simple_crew_table(package, table="p943-t1", output_row="시공량", output_column={"column": "수량"},
                      crew=["특별인부", "보통인부"], equipment=["트럭"], quantity_input="quantity",
                      steps=GENERIC_STEPS, source="PDF 2-1-21 표 및 [주]", reason=GENERIC_REASON)


@promotion("유지관리/2-1-12")
def manhole_fall_net(package: dict) -> None:
    spec = package["draft"]
    # [주] ④⑤③은 '별도 계상'이다. 계산을 막는 조건이 아니라 미산정 항목이므로 질문·보류를 없애고 not_calculated로 둔다.
    spec["inputs"] = [i for i in spec["inputs"] if i["name"] not in ("internal_plastering", "waste_disposal", "other_cutter")]
    spec["blocked"] = []
    retype(package, "p937-t0", {
        "포장공": {"수량": "2"}, "특별인부": {"수량": "2"}, "보통인부": {"수량": "1"},
        "굴착기": {"수량": "1"}, "커터(콘크리트 및 아스팔트용)": {"수량": "1"}, "소형브레이커(전기식)": {"수량": "1"},
        "플레이트콤팩터": {"수량": "1"}, "덤프트럭": {"수량": "3"}, "시공량": {"수량": "8"}})
    simple_crew_table(package, table="p937-t0", output_row="시공량", output_column={"column": "수량"},
                      crew=["포장공", "특별인부", "보통인부"],
                      equipment=["굴착기", "커터(콘크리트 및 아스팔트용)", "소형브레이커(전기식)", "플레이트콤팩터", "덤프트럭"],
                      quantity_input="quantity", steps=GENERIC_STEPS, source="PDF 2-1-12 표 및 [주]",
                      reason=GENERIC_REASON + " 내부미장·폐자재 처리·다른 절단장비는 원문이 별도 계상하라는 항목이라 미산정으로 둔다.")


@promotion("유지관리/2-4-2")
def sewer_cleaning(package: dict) -> None:
    retype(package, "p959-t1", {
        "배관공(수도)": {"수량": "3"}, "보통인부": {"수량": "1"}, "진공흡입준설차": {"수량": "1"},
        "물탱크(살수차)": {"수량": "1"}, "시공량": {"A-Type": "340", "B-Type": "260"}})
    simple_crew_table(
        package, table="p959-t1", output_row="시공량", output_column={"column_input": "site_type"},
        crew=["배관공(수도)", "보통인부"], equipment=["진공흡입준설차", "물탱크(살수차)"], quantity_input="quantity",
        steps=["Type 열의 일당 시공량(m)을 고른다.", "준설 작업이 필요 없으면 시공량을 20% 증가한다.",
               "물량 ÷ 시공량으로 작업일수를 구하고 인원·장비 대수를 곱한다."],
        source="PDF 2-4-2 표 및 비고", reason=GENERIC_REASON + " 비고의 시공량 20% 증가를 출력 보정으로 표현한다.",
        extra={"output_adjustments": [{
            "when": {"dredging_required": False}, "operation": "multiply_output", "value": "6/5",
            "source": "표 비고: 준설 작업이 필요하지 않은 경우에는 시공량의 20%를 증가하여 적용한다",
            "cite": {"table_id": "p959-t1"}}]})


@promotion("유지관리/3-3-2")
def rust_surface_prep(package: dict) -> None:
    retype(package, "p974-t1", {"도장공": {"수량": "2"}, "보통인부": {"수량": "1"},
                                "시공량": {"A급": "20", "B급": "60"}})
    simple_crew_table(package, table="p974-t1", output_row="시공량", output_column={"column_input": "surface_condition"},
                      crew=["도장공", "보통인부"], equipment=[], quantity_input="quantity", steps=GENERIC_STEPS,
                      source="PDF 3-3-2 표 및 [주]", reason=GENERIC_REASON)


@promotion("유지관리/3-4-1")
def roof_overlay(package: dict) -> None:
    package["draft"]["blocked"] = []
    retype(package, "p975-t0", {"지붕잇기공": {"수량": "4"}, "보통인부": {"수량": "2"}, "시공량": {"수량": "85"}})
    simple_crew_table(
        package, table="p975-t0", output_row="시공량", output_column={"column": "수량"},
        crew=["지붕잇기공", "보통인부"], equipment=[], quantity_input="quantity",
        steps=["일당 시공량 85㎡로 물량 ÷ 시공량 = 작업일수를 구한다.", "맞배지붕은 시공량을 20% 가산한다.",
               "작업일수 × 직종별 인원으로 총 투입량을 구한다."],
        source="PDF 3-4-1 표 및 비고", reason=GENERIC_REASON + " 비고의 맞배지붕 20% 가산을 출력 보정으로 표현한다.",
        extra={"output_adjustments": [{
            "when": {"roof_type": "맞배지붕"}, "operation": "multiply_output", "value": "6/5",
            "source": "표 비고: 맞배지붕은 시공량을 20% 가산하여 적용한다", "cite": {"table_id": "p975-t0"}}]})


@promotion("유지관리/3-4-4")
def pvc_floor_replace(package: dict) -> None:
    retype(package, "p976-t0", {"내장공": {"수량": "2"}, "시공량": {"수량": "61"}})
    simple_crew_table(
        package, table="p976-t0", output_row="시공량", output_column={"column": "수량"},
        crew=["내장공"], equipment=[], quantity_input="quantity",
        steps=["일당 시공량 61㎡로 물량 ÷ 시공량 = 작업일수를 구한다.",
               "사용중인 세대로 지장물이 있으면 시공량의 15%를 감한다.", "작업일수 × 내장공 2인으로 총 투입량을 구한다."],
        source="PDF 3-4-4 표 및 비고", reason=GENERIC_REASON + " 비고의 지장물 15% 감을 출력 보정으로 표현한다.",
        extra={"output_adjustments": [{
            "when": {"has_obstacle": True}, "operation": "set_output_percent", "value": "15",
            "source": "표 비고: 사용중인 세대로 가구 등의 지장물이 있는 경우 시공량의 15%를 감한다",
            "cite": {"table_id": "p976-t0"}}]})


def milling_overlay(package: dict, *, table: str, section: str, types_input: str, outputs: tuple, crew: dict,
                    equipment: dict, quantity: str, roundabout: str) -> None:
    """절삭 후 덧씌우기: Type별 인원·장비·시공량, 일당시공량 내 회전교차로 1개소 포함 시 시공량 17% 감."""
    spec = package["draft"]
    types = field(spec, types_input)["allowed_values"]
    values = {trade: dict(zip(types, counts)) for trade, counts in crew.items()}
    values.update({name: dict(zip(types, counts)) for name, counts in equipment.items()})
    values["시공량"] = dict(zip(types, outputs))
    retype(package, table, values)
    spec["blocked"] = []
    trades = list(crew)
    finish(package, "daily_crew",
           "Type별 인원·장비 대수·일당 시공량이 표에 있고 회전교차로 포함 시 17% 감은 출력 보정으로 표현된다. "
           "절삭 팁(날) 수량은 절삭 체적 기준이라 미산정으로 둔다.",
           ["Type 열의 일당 시공량(㎡)을 고른다.", "일당시공량 내 회전교차로 1개소를 포함하면 시공량의 17%를 감한다.",
            "물량 ÷ 시공량으로 작업일수를 구하고 인원·장비 대수를 곱한다."],
           {"quantity_input": quantity,
            "base_output": {"table": table, "row": "시공량", "column_input": types_input},
            "coefficients": [],
            "crew": {"table": table, "column_input": types_input, "trades": trades,
                     "rate_codes": {n: "" for n in trades}},
            "equipment": [{"name": name, "table": table, "column_input": types_input, "unit": "대·일"}
                          for name in equipment],
            "output_adjustments": [{
                "when": {roundabout: True}, "operation": "set_output_percent", "value": "17",
                "source": "표 비고: 일당시공량 내에 회전교차로 1개소를 포함한 경우는 시공량의 17%를 감하여 적용한다",
                "cite": {"table_id": table}}]},
           source=f"PDF {section} 표 및 [주]")


@promotion("유지관리/2-1-3")
def milling_overlay_1x1(package: dict) -> None:
    milling_overlay(
        package, table="p929-t1", section="2-1-3", types_input="type", outputs=("5000", "3400", "1800"),
        crew={"포장공": ("4", "4", "4"), "보통인부": ("2", "2", "2")},
        equipment={"노면파쇄기 2m": ("2", "2", "1"), "로더(타이어)+소형노면파쇄기 0.95㎥": ("1", "1", "1"),
                   "로더(타이어) 0.57㎥": ("3", "2", "1"), "아스팔트피니셔 3.0m": ("1", "1", "1"),
                   "머캐덤롤러 10∼12t": ("1", "1", "1"), "타이어롤러 8∼15t": ("1", "1", "1"),
                   "탠덤롤러 5∼8t": ("1", "1", "1"), "아스팔트디스트리뷰터 3,800L": ("1", "1", "1"),
                   "살수차 16,000ℓ": ("1", "1", "1")},
        quantity="volume", roundabout="roundabout_included")


@promotion("유지관리/2-1-4")
def milling_overlay_1x2(package: dict) -> None:
    spec = package["draft"]
    spec["inputs"] = [i for i in spec["inputs"] if i["name"] != "milling_volume"]  # 팁 수량 산정용: 미산정
    milling_overlay(
        package, table="p930-t1", section="2-1-4", types_input="site_type", outputs=("2600", "1800"),
        crew={"포장공": ("4", "4"), "보통인부": ("2", "2")},
        equipment={"노면파쇄기 2m": ("2", "2"), "로더(타이어)+소형노면파쇄기 0.95㎥": ("1", "1"),
                   "로더(타이어) 0.57㎥": ("3", "2"), "아스팔트피니셔 3.0m": ("1", "1"),
                   "머캐덤롤러 10∼12t": ("1", "1"), "타이어롤러 8∼15t": ("1", "1"), "탠덤롤러 5∼8t": ("1", "1"),
                   "아스팔트디스트리뷰터 3,800L": ("1", "1"), "살수차 16,000ℓ": ("1", "1")},
        quantity="quantity", roundabout="roundabout_included")


@promotion("유지관리/2-1-5")
def milling_concrete_overlay(package: dict) -> None:
    spec = package["draft"]
    upsert_input(spec, {"name": "milling_depth", "type": "enum", "allowed_values": ["100㎜", "150㎜"], "unit": "㎜",
                        "required": True, "ask": "절삭(밀링) 깊이는 100㎜입니까, 150㎜입니까?",
                        "source": "PDF 2-1-5 표 시공량 구분(밀링깊이)"})
    upsert_input(spec, {"name": "quantity", "type": "positive_rational", "allowed_values": "0보다 큰 수", "unit": "㎡",
                        "required": True, "ask": "절삭 후 콘크리트 덧씌우기 면적은 몇 ㎡입니까?",
                        "source": "PDF 2-1-5 표 시공량 단위"})
    # 보통인부는 절삭 1·청소 1·포설 4로 나뉘어 적히며 노임 직종이 같으므로 합계 6인으로 옮긴다.
    retype(package, "p931-t0", {
        "포장공": {"수량": "4"}, "특별인부": {"수량": "1"}, "보통인부": {"수량": "6"},
        "콘크리트페이버 75㎾": {"수량": "1"}, "조면마무리기 7.95m": {"수량": "1"}, "노면파쇄기 2m": {"수량": "1"},
        "로더(타이어) 0.57㎥": {"수량": "1"}, "시공량": {"100㎜": "2500", "150㎜": "1600"}})
    crew = ["포장공", "특별인부", "보통인부"]
    finish(package, "daily_crew",
           "밀링깊이별 일당 시공량과 인원·장비 대수가 표에 있어 기존 일당 작업조 계산기로 표현된다. "
           "보통인부(절삭 1·청소 1·포설 4)는 같은 노임 직종이라 6인으로 합산해 옮겼다.",
           ["밀링깊이 열의 일당 시공량(㎡)을 고른다.", "면적 ÷ 시공량으로 작업일수를 구한다.",
            "작업일수 × 직종별 인원, × 장비 대수로 총 투입량을 구한다."],
           {"quantity_input": "quantity",
            "base_output": {"table": "p931-t0", "row": "시공량", "column_input": "milling_depth"},
            "coefficients": [],
            "crew": {"table": "p931-t0", "column": "수량", "trades": crew, "rate_codes": {n: "" for n in crew}},
            "equipment": [{"name": name, "table": "p931-t0", "column": "수량", "unit": "대·일"}
                          for name in ("콘크리트페이버 75㎾", "조면마무리기 7.95m", "노면파쇄기 2m", "로더(타이어) 0.57㎥")]},
           source="PDF 2-1-5 표 및 [주]")


@promotion("유지관리/2-1-6")
def asphalt_milling_and_overlay(package: dict) -> None:
    spec = package["draft"]
    upsert_input(spec, {**field(spec, "pavement_type"), "when": {"input": "work_type", "equals": "덧씌우기 포장"}})
    spec["crew_rules"] = []
    spec["blocked"] = []
    retype(package, "p932-t0", {
        "포장공": {"절삭": "2", "덧씌우기 포장": "4"}, "보통인부": {"절삭": "1", "덧씌우기 포장": "1"},
        "노면파쇄기 2m": {"절삭": "1"}, "로더(타이어)+소형노면파쇄기 0.95㎥": {"절삭": "1"},
        "로더(타이어) 0.57㎥": {"절삭": "2", "덧씌우기 포장": "1"}, "아스팔트피니셔 3.0m": {"덧씌우기 포장": "1"},
        "머캐덤롤러 10∼12t": {"덧씌우기 포장": "1"}, "타이어롤러 8∼15t": {"덧씌우기 포장": "1"},
        "탠덤롤러 5∼8t": {"덧씌우기 포장": "1"}, "플레이트콤팩터 1.5ton": {"덧씌우기 포장": "1"},
        "살수차 16,000ℓ": {"절삭": "1", "덧씌우기 포장": "1"}, "아스팔트스프레이어 400ℓ": {"덧씌우기 포장": "1"},
        "시공량": {"절삭": "2900", "덧씌우기 포장": "2000"}})

    def eq(name, column, **extra):
        return {"name": name, "table": "p932-t0", "column": column, "unit": "대·일", **extra}

    cut = [eq(n, "절삭", when={"work_type": "절삭"}) for n in
           ("노면파쇄기 2m", "로더(타이어)+소형노면파쇄기 0.95㎥", "로더(타이어) 0.57㎥", "살수차 16,000ℓ")]
    overlay_common = [eq(n, "덧씌우기 포장", when={"work_type": "덧씌우기 포장"}) for n in
                      ("로더(타이어) 0.57㎥", "아스팔트피니셔 3.0m", "머캐덤롤러 10∼12t", "탠덤롤러 5∼8t",
                       "플레이트콤팩터 1.5ton", "살수차 16,000ℓ", "아스팔트스프레이어 400ℓ")]
    tire = [eq("타이어롤러 8∼15t", "덧씌우기 포장",
               when={"work_type": "덧씌우기 포장", "pavement_type": "일반아스팔트"})]
    # 비고: 개질·투배수성은 타이어롤러 대신 머캐덤롤러(10∼12t) 1대를 추가 계상한다.
    extra_macadam = [{"name": "머캐덤롤러 10∼12t", "count": "1", "unit": "대·일",
                      "when": {"work_type": "덧씌우기 포장", "pavement_type": kind},
                      "source": "표 비고: 개질/투배수성은 타이어롤러 대신 머캐덤롤러(10∼12t) 1대를 추가 계상",
                      "cite": {"table_id": "p932-t0"}} for kind in ("개질아스팔트", "투배수성")]
    crew = ["포장공", "보통인부"]
    finish(package, "daily_crew",
           "절삭/덧씌우기 포장 열별 인원·장비·시공량이 표에 있고 비고의 포장 종류별 시공량 감·롤러 교체를 기존 필드로 표현한다.",
           ["작업 종류 열의 일당 시공량(㎡)을 고른다.", "덧씌우기에서 개질아스팔트는 10%, 투배수성은 20% 시공량을 감한다.",
            "개질·투배수성은 타이어롤러 대신 머캐덤롤러 1대를 추가 계상한다.",
            "물량 ÷ 시공량으로 작업일수를 구하고 인원·장비 대수를 곱한다."],
           {"quantity_input": "quantity",
            "base_output": {"table": "p932-t0", "row": "시공량", "column_input": "work_type"},
            "coefficients": [],
            "crew": {"table": "p932-t0", "column_input": "work_type", "trades": crew,
                     "rate_codes": {n: "" for n in crew}},
            "equipment": cut + overlay_common + tire + extra_macadam,
            "output_adjustments": [
                {"when": {"work_type": "덧씌우기 포장", "pavement_type": "개질아스팔트"},
                 "operation": "set_output_percent", "value": "10",
                 "source": "표 비고: 개질아스팔트 포장의 경우 10% 시공량을 감한다", "cite": {"table_id": "p932-t0"}},
                {"when": {"work_type": "덧씌우기 포장", "pavement_type": "투배수성"},
                 "operation": "set_output_percent", "value": "20",
                 "source": "표 비고: 투배수성 포장의 경우 20% 시공량을 감한다", "cite": {"table_id": "p932-t0"}}]},
           source="PDF 876쪽 2-1-6 표 및 비고")


@promotion("토목/1-5-2")
def asphalt_base_tiny(package: dict) -> None:
    spec = package["draft"]
    table = {"id": "p367-t0", "role": "배치인원·장비 대수와 일당 시공량", "source": "PDF 311쪽 1-5-2 표",
             "unit": "인, 대, ㎡/일",
             "values": {"포장공": {"수량": "2"}, "보통인부": {"수량": "1"}, "플레이트콤팩터 1.5ton": {"수량": "1"},
                        "진동롤러(핸드가이드식) 0.7ton": {"수량": "1"}, "로더(타이어) 0.57㎥": {"수량": "1"},
                        "살수차 5,500L": {"수량": "0.5"}, "시공량": {"수량": "320"}},
             "cite": {"table_id": "p367-t0"}}
    spec["tables"] = [t for t in spec["tables"] if t["id"] != "p367-t0"] + [table]
    refresh_table_citations(package, "p367-t0")
    simple_crew_table(
        package, table="p367-t0", output_row="시공량", output_column={"column": "수량"},
        crew=["포장공", "보통인부"],
        equipment=["플레이트콤팩터 1.5ton", "진동롤러(핸드가이드식) 0.7ton", "로더(타이어) 0.57㎥", "살수차 5,500L"],
        quantity_input="volume", steps=GENERIC_STEPS, source="PDF 311쪽 1-5-2 표 및 [주]", reason=GENERIC_REASON)


@promotion("토목/1-5-1")
def prime_coat_spray(package: dict) -> None:
    spec = package["draft"]
    spec["blocked"] = []
    spec["inputs"] = [i for i in spec["inputs"] if i["name"] not in ("need_anti_scattering", "need_sand_curing")]
    flag = {"type": "boolean", "allowed_values": [True, False], "unit": None, "required": True}
    upsert_input(spec, {**flag, "name": "need_anti_scattering", "ask": "역청재의 비산 방지가 필요합니까?",
                        "source": "PDF 1-5-1 비고"})
    upsert_input(spec, {"name": "bitumen_liters", "type": "positive_rational", "allowed_values": "0보다 큰 수",
                        "unit": "ℓ", "required": True, "when": {"input": "need_anti_scattering", "equals": True},
                        "ask": "비산 방지가 필요한 역청재 살포량은 몇 ℓ입니까?", "source": "PDF 1-5-1 비고(2,000ℓ당 1인)"})
    upsert_input(spec, {**flag, "name": "need_sand_curing", "ask": "양생에 모래가 필요합니까?",
                        "source": "PDF 1-5-1 비고"})
    upsert_input(spec, {"name": "sand_volume", "type": "positive_rational", "allowed_values": "0보다 큰 수",
                        "unit": "㎥", "required": True, "when": {"input": "need_sand_curing", "equals": True},
                        "ask": "양생에 사용하는 모래는 몇 ㎥입니까?", "source": "PDF 1-5-1 비고(모래 2㎥당 1인)"})
    retype(package, "p366-t2", {
        "보통인부": {"인력식": "2", "기계식": "1"},
        "아스팔트스프레어(수동식 살포기) 400ℓ": {"인력식": "1"},
        "아스팔트디스트리뷰터(폭 2.4m) 3,800ℓ": {"기계식": "1"},
        "시공량": {"인력식": "8000", "기계식": "20000"}})
    note = {"table_id": "p366-t2"}
    simple_crew_table(
        package, table="p366-t2", output_row="시공량", output_column={"column_input": "method"},
        crew=["보통인부"], equipment=[], quantity_input="area", crew_column={"column_input": "method"},
        steps=["살포 방식(인력식/기계식)의 일당 시공량(㎡)을 고른다.", "면적 ÷ 시공량으로 작업일수를 구한다.",
               "작업일수 × 보통인부 수, × 살포 장비 1대로 총 투입량을 구한다.",
               "비산 방지가 필요하면 역청재 2,000ℓ당 보통인부 1인, 양생 모래가 필요하면 모래 2㎥당 1인을 더한다."],
        source="PDF 1-5-1 표 및 비고", reason=GENERIC_REASON + " 비고의 수량당 인원 가산은 additional_unit_labor로 표현한다.",
        extra={"equipment": [
            {"name": "아스팔트스프레어(수동식 살포기) 400ℓ", "table": "p366-t2", "column": "인력식", "unit": "대·일",
             "when": {"method": "인력식"}},
            {"name": "아스팔트디스트리뷰터(폭 2.4m) 3,800ℓ", "table": "p366-t2", "column": "기계식", "unit": "대·일",
             "when": {"method": "기계식"}}],
            "additional_unit_labor": [
                {"when": {"need_anti_scattering": True}, "trade": "보통인부", "quantity_input": "bitumen_liters",
                 "unit": "인/2,000ℓ", "rate": "1", "basis": "2,000ℓ", "cite": note,
                 "source": "비고: 역청재의 비산 방지가 필요한 때는 보통인부를 2,000ℓ당 1인을 가산한다"},
                {"when": {"need_sand_curing": True}, "trade": "보통인부", "quantity_input": "sand_volume",
                 "unit": "인/2㎥", "rate": "1", "basis": "2㎥", "cite": note,
                 "source": "비고: 양생에 모래가 필요할 때는 살포 인력품으로 보통인부를 모래 2㎥당 1인을 가산한다"}]})


def per_unit_single_column(package: dict, *, table: str, values: dict, unit: str, trades: list[str], quantity: str,
                           reason: str, source: str, steps: list[str], resource_units: dict | None = None) -> None:
    """한 열짜리 단위당 품 표(행=직종/장비, 열=수량)를 per_unit 계산기로 연결한다."""
    retype(package, table, values)
    next(t for t in package["draft"]["tables"] if t["id"] == table)["unit"] = unit
    finish(package, "per_unit", reason, steps,
           {"unit_rate_table": {"table": table, "row_input": "고정 행이름", "column_input": "수량", "trades": trades,
                                **({"resource_units": resource_units} if resource_units else {})},
            "quantity_input": quantity, "surcharges": [], "note_adjustments": []},
           model="per_unit", source=source)


@promotion("토목/4-6-10")
def wooden_sleeper_fastener(package: dict) -> None:
    per_unit_single_column(
        package, table="p409-t0", values={"궤도공": {"수량": "0.028"}, "보통인부": {"수량": "0.022"}},
        unit="인/개소", trades=["궤도공", "보통인부"], quantity="quantity",
        reason="침목 개소당 직종별 품이 표에 직접 있어 단위당 품 계산기로 표현된다.",
        steps=["표의 개소당 품에 설치 개소를 곱한다."], source="PDF 4-6-10 표")


@promotion("토목/2-2-2")
def mattress_gabion(package: dict) -> None:
    per_unit_single_column(
        package, table="p390-t0",
        values={"석공": {"수량": "0.027"}, "특별인부": {"수량": "0.010"}, "보통인부": {"수량": "0.010"},
                "굴착기": {"수량": "0.025"}},
        unit="인/㎡, hr/㎡", trades=["석공", "특별인부", "보통인부", "굴착기"], quantity="quantity",
        resource_units={"굴착기": "hr"},
        reason="㎡당 직종별 인·일과 굴착기 시간이 표에 직접 있어 단위당 품 계산기로 표현된다.",
        steps=["표의 ㎡당 품(인)과 굴착기 시간(hr)에 설치 면적을 곱한다."], source="PDF 2-2-2 표")


@promotion("유지관리/1-2-10")
def weeding(package: dict) -> None:
    spec = package["draft"]
    zones = ["일반 잔디지역", "지장물 지역"]
    upsert_input(spec, {"name": "area_condition", "type": "enum", "allowed_values": zones, "unit": None,
                        "required": True, "ask": "제초 대상지는 일반 잔디지역입니까, 지장물 지역입니까?",
                        "source": "PDF 1-2-10 표 시공량 구분 및 [주] ② (지장물 지역 정의)"})
    retype(package, "p919-t0", {"조경공": {"수량": "1"}, "보통인부": {"수량": "5"},
                                "시공량": dict(zip(zones, ("1400", "1000")))})
    simple_crew_table(
        package, table="p919-t0", output_row="시공량", output_column={"column_input": "area_condition"},
        crew=["조경공", "보통인부"], equipment=[], quantity_input="area",
        steps=["대상지 구분(일반 잔디지역/지장물 지역)의 일당 시공량(㎡)을 고른다.", "면적 ÷ 시공량으로 작업일수를 구한다.",
               "작업일수 × 직종별 인원으로 총 투입량을 구한다."],
        source="PDF 1-2-10 표 및 [주]", reason=GENERIC_REASON)


@promotion("유지관리/1-2-12")
def mowing(package: dict) -> None:
    spec = package["draft"]
    retype(package, "p920-t0", {"특별인부": {"수량": "3"}, "보통인부": {"수량": "1"}, "시공량": {"수량": "2500"}})
    both = "연간 시공횟수 할증과 경사도 할증이 함께 적용되는 경우"
    spec["blocked"] = [
        {"condition": f"{both} ({times})", "blocked_if_all": [
            {"input": "frequency", "op": "==", "value": times},
            {"input": "slope_25_over", "op": "==", "value": True}],
         "reason": "연간 시공횟수 할증(-30%/-20%)과 경사도 할증(-10%)이 함께 적용될 때 누적 방식(합산/곱)이 원문에 명시되어 있지 않다.",
         "source": "PDF 1-2-12 비고", "cite": {"table_id": "p920-t1"}}
        for times in ("연1회", "연2회")]
    crew = ["특별인부", "보통인부"]
    note = {"table_id": "p920-t1"}
    simple_crew_table(
        package, table="p920-t0", output_row="시공량", output_column={"column": "수량"}, crew=crew, equipment=[],
        quantity_input="area",
        steps=["일당 시공량 2,500㎡(연 3회 이상 기준)로 면적 ÷ 시공량 = 작업일수를 구한다.",
               "연 1회는 시공량의 30%, 연 2회는 20%, 경사 25˚ 이상은 10%를 감한다(둘이 겹치면 원문이 정하지 않아 보류).",
               "돌튐 방지 그물막이가 필요하면 보통인부 2인을 추가한다."],
        source="PDF 1-2-12 표 및 비고", reason=GENERIC_REASON + " 비고의 시공량 감과 그물막 인원 가산을 기존 보정 필드로 표현한다.",
        extra={"output_adjustments": [
            {"when": {"frequency": "연1회", "slope_25_over": False}, "operation": "set_output_percent", "value": "30",
             "source": "비고: 연 1회 시공량 할증율 -30%", "cite": note},
            {"when": {"frequency": "연2회", "slope_25_over": False}, "operation": "set_output_percent", "value": "20",
             "source": "비고: 연 2회 시공량 할증율 -20%", "cite": note},
            {"when": {"frequency": "연3회 이상", "slope_25_over": True}, "operation": "set_output_percent", "value": "10",
             "source": "비고: 경사도 25˚ 이상 시공량 할증률 -10%", "cite": note}]})


@promotion("유지관리/1-2-13")
def tree_fertilizing(package: dict) -> None:
    spec = package["draft"]
    bands = ["11㎝ 미만", "11∼21㎝ 미만", "21∼31㎝ 미만", "31∼41㎝ 미만", "41∼51㎝ 미만", "51㎝ 이상"]
    upsert_input(spec, {**field(spec, "root_diameter"), "allowed_values": bands})
    retype(package, "p920-t2", {
        "조경공": {"수량": "2"}, "보통인부": {"수량": "1"},
        "환상시비": dict(zip(bands, ("76", "61", "51", "44", "38", "34"))),
        "방사형시비": dict(zip(bands, ("100", "82", "69", "59", "52", "46")))})
    simple_crew_table(
        package, table="p920-t2", output_row="work_type", output_column={"column_input": "root_diameter"},
        crew=["조경공", "보통인부"], equipment=[], quantity_input="quantity",
        steps=["작업구분(환상/방사형)과 근원직경 구간의 일당 시공량(주)을 고른다.", "수량 ÷ 시공량으로 작업일수를 구한다.",
               "작업일수 × 직종별 인원으로 총 투입량을 구한다. 비료 수량·재료비는 미산정."],
        source="PDF 1-2-13 표 및 [주]", reason=GENERIC_REASON)


@promotion("유지관리/1-2-20")
def street_tree_removal(package: dict) -> None:
    spec = package["draft"]
    bands = field(spec, "diameter")["allowed_values"]
    cut = dict(zip(bands, ("48", "32", "20", "13", "8", "5", "3")))
    root = dict(zip(bands, ("37", "25", "15", "10", "6", "4", "3")))
    retype(package, "p922-t3", {
        "벌목부": {"수량": "2"}, "보통인부": {"수량": "3"}, "굴착기+부착용집게": {"수량": "1"}, "고소작업차": {"수량": "1"},
        **{band: {"수량": value} for band, value in cut.items()}})
    retype(package, "p923-t0", {
        "특별인부": {"수량": "2"}, "보통인부": {"수량": "1"}, "굴착기+브레이커": {"수량": "1"},
        **{band: {"수량": value} for band, value in root.items()}})
    spec["cost_rules"] = [{**spec["cost_rules"][0], "when": {"work_type": "나무베기"}}]
    route = {"input": "work_type", "values": {"나무베기": "p922-t3", "뿌리제거": "p923-t0"}}
    trades = {"나무베기": ["벌목부", "보통인부"], "뿌리제거": ["특별인부", "보통인부"]}
    finish(package, "daily_crew",
           "작업 종류(나무베기/뿌리제거)별 표에서 인원·장비와 흉고직경 구간별 일당 시공량을 읽는 일당 작업조 구조다. "
           "원문 요율표의 뿌리제거 '-'는 요율이 없다는 뜻이라 공구손료 규칙을 나무베기에만 둔다.",
           ["작업 종류에 해당하는 표를 고른다.", "흉고직경 구간의 일당 시공량(주)을 읽고 수량 ÷ 시공량으로 작업일수를 구한다.",
            "작업일수 × 직종별 인원, × 장비 대수로 총 투입량을 구한다."],
           {"quantity_input": "quantity",
            "base_output": {"table_selector": route, "row_input": "diameter", "column": "수량"},
            "coefficients": [],
            "crew": {"table_selector": route, "column": "수량", "trade_selector_input": "work_type",
                     "trades_by_input": trades, "rate_codes": {n: "" for t in trades.values() for n in t}},
            "equipment": [
                {"name": "굴착기+부착용집게", "table": "p922-t3", "column": "수량", "unit": "대·일",
                 "when": {"work_type": "나무베기"}},
                {"name": "고소작업차", "table": "p922-t3", "column": "수량", "unit": "대·일",
                 "when": {"work_type": "나무베기"}},
                {"name": "굴착기+브레이커", "table": "p923-t0", "column": "수량", "unit": "대·일",
                 "when": {"work_type": "뿌리제거"}}]},
           source="PDF 866~867쪽 1-2-20 표 및 [주]")


@promotion("유지관리/1-2-4")
def street_tree_pruning(package: dict) -> None:
    spec = package["draft"]
    spec["inputs"] = [i for i in spec["inputs"] if i["name"] != "machine_spec"]  # 선택지가 하나뿐인 질문은 두지 않는다
    bands = field(spec, "diameter")["allowed_values"]
    rows = {"약전정": ("31", "21", "16", "12", "10", "8", "7"), "강전정": ("19", "14", "10", "8", "7", "6", "5"),
            "조형전정": ("17", "12", "9", "7", "6", "4", "3")}
    retype(package, "p916-t1", {"조경공": {"수량": "2"}, "보통인부": {"수량": "2"}, "고소작업차": {"수량": "1"},
                                **{kind: dict(zip(bands, values)) for kind, values in rows.items()}})
    simple_crew_table(
        package, table="p916-t1", output_row="work_type", output_column={"column_input": "diameter"},
        crew=["조경공", "보통인부"], equipment=["고소작업차"], quantity_input="quantity",
        steps=["작업구분(약/강/조형 전정)과 흉고직경 구간의 일당 시공량(주)을 고른다.", "수량 ÷ 시공량으로 작업일수를 구한다.",
               "작업일수 × 직종별 인원, × 고소작업차 1대로 총 투입량을 구한다."],
        source="PDF 860쪽 1-2-4 표 및 [주]", reason=GENERIC_REASON)


@promotion("유지관리/1-2-15")
def turf_fertilizing(package: dict) -> None:
    spec = package["draft"]
    upsert_input(spec, {"name": "spread_rate", "type": "positive_rational", "allowed_values": "0보다 큰 수",
                        "unit": "kg/10,000㎡", "required": True,
                        "ask": "화학비료 살포량은 10,000㎡당 몇 kg입니까?", "source": "PDF 1-2-15 [주] ①"})
    cite = {"table_id": "p921-t1"}
    spec["blocked"] = [
        {"condition": f"화학비료 살포량이 {limit}㎏/10,000㎡ {word}", "blocked_if": {"input": "spread_rate", "op": op, "value": limit},
         "reason": "본 품은 화학비료 살포량 300∼700㎏/10,000㎡ 기준이다. 범위를 벗어나는 경우는 원문이 별도 산정을 요구한다.",
         "source": "PDF 865쪽 1-2-15 [주] ①", "cite": cite}
        for op, limit, word in (("<", "300", "미만"), (">", "700", "초과"))]
    spec["not_calculated"] = spec["not_calculated"] + [
        {"item": "현장조건·살포조건에 따른 시공량 20% 범위 내 증감", "source": "PDF 1-2-15 [주] ② (율을 원문이 정하지 않음)", "cite": cite}]
    retype(package, "p921-t1", {"조경공": {"수량": "2"}, "보통인부": {"수량": "1"}, "트럭 2.5ton": {"수량": "1"},
                                "시공량": {"수량": "22500"}})
    simple_crew_table(
        package, table="p921-t1", output_row="시공량", output_column={"column": "수량"},
        crew=["조경공", "보통인부"], equipment=["트럭 2.5ton"], quantity_input="quantity",
        steps=["일당 시공량 22,500㎡로 면적 ÷ 시공량 = 작업일수를 구한다.",
               "작업일수 × 직종별 인원, × 트럭 1대로 총 투입량을 구한다.", "살포량이 300∼700㎏/10,000㎡ 밖이면 보류한다."],
        source="PDF 865쪽 1-2-15 표 및 [주]", reason=GENERIC_REASON)


@promotion("유지관리/1-3-4")
def crack_filling(package: dict) -> None:
    spec = package["draft"]
    spec["inputs"] = [i for i in spec["inputs"] if i["name"] != "equipment_needed"]  # [주] ⑤ 별도 계상: 미산정
    retype(package, "p924-t1", {"특별인부": {"수량": "1"}, "보통인부": {"수량": "1"}, "시공량": {"수량": "23"}})
    simple_crew_table(
        package, table="p924-t1", output_row="시공량", output_column={"column": "수량"},
        crew=["특별인부", "보통인부"], equipment=[], quantity_input="quantity",
        steps=["일당 시공량 23m로 길이 ÷ 시공량 = 작업일수를 구한다.", "작업일수 × 직종별 인원으로 총 투입량을 구한다.",
               "균열폭 10㎜ 초과·형태가 다양한 경우는 원문이 적의 산출하라고 하여 보류한다."],
        source="PDF 1-3-4 표 및 [주]", reason=GENERIC_REASON)


@promotion("유지관리/2-4-1")
def water_pipe_flushing(package: dict) -> None:
    retype(package, "p959-t0", {"배관공(수도)": {"수량": "1"}, "보통인부": {"수량": "3"}, "시험기구": {"수량": "1"},
                                "시공량": {"수량": "2"}})
    simple_crew_table(
        package, table="p959-t0", output_row="시공량", output_column={"column": "수량"},
        crew=["배관공(수도)", "보통인부"], equipment=[], quantity_input="quantity",
        steps=["일당 시공량 2구간으로 구간 수 ÷ 2 = 작업일수를 구한다.", "작업일수 × 직종별 인원으로 총 투입량을 구한다.",
               "시험기구(1식)의 손료는 원문이 별도 계상하라고 하여 미산정으로 둔다. 관경 300㎜ 초과는 보류한다."],
        source="PDF 2-4-1 표 및 [주]", reason=GENERIC_REASON)


@promotion("유지관리/2-4-7")
def sewer_dredging(package: dict) -> None:
    spec = package["draft"]
    # 장비 규격은 Type에 따라 정해진다(표 ⑤). 같은 정보를 다시 묻지 않는다.
    spec["inputs"] = [i for i in spec["inputs"] if i["name"] not in ("dredger_size", "water_tank_size")]
    spec["blocked"] = []
    retype(package, "p962-t0", {
        "배관공(수도)": {"수량": "2"}, "보통인부": {"수량": "1"}, "진공흡입준설차": {"수량": "1"},
        "물탱크(살수차)": {"수량": "1"}, "시공량": {"A-Type": "8.6", "B-Type": "6.4"}})
    simple_crew_table(
        package, table="p962-t0", output_row="시공량", output_column={"column_input": "site_type"},
        crew=["배관공(수도)", "보통인부"], equipment=["진공흡입준설차", "물탱크(살수차)"], quantity_input="volume",
        steps=["Type 열의 일당 시공량(㎥)을 고른다.", "폐기물 등으로 세정 이외의 추가작업이 필요하면 시공량의 15%를 감한다.",
               "물량 ÷ 시공량으로 작업일수를 구하고 인원·장비 대수를 곱한다. 세정수 양은 미산정."],
        source="PDF 2-4-7 표 및 비고", reason=GENERIC_REASON + " 비고의 시공량 15% 감을 출력 보정으로 표현한다.",
        extra={"output_adjustments": [{
            "when": {"extra_work": True}, "operation": "set_output_percent", "value": "15",
            "source": "비고: 폐기물 등으로 준설차 세정 이외의 추가작업이 필요한 경우 시공량을 15% 감한다",
            "cite": {"table_id": "p962-t0"}}]})


@promotion("유지관리/2-2-16")
def sleeper_fastener_removal(package: dict) -> None:
    per_unit_single_column(
        package, table="p957-t1", values={"궤도공": {"수량": "0.028"}, "보통인부": {"수량": "0.022"}},
        unit="인/개소", trades=["궤도공", "보통인부"], quantity="quantity",
        reason="침목 개소당 직종별 품이 표에 직접 있어 단위당 품 계산기로 표현된다.",
        steps=["표의 개소당 품에 철거 개소를 곱한다."], source="PDF 2-2-16 표")


@promotion("유지관리/1-1-3")
def slope_inspection_path(package: dict) -> None:
    retype(package, "p914-t1", {"철공": {"수량": "4"}, "보통인부": {"수량": "1"}, "시공량": {"수량": "7.8"}})
    simple_crew_table(
        package, table="p914-t1", output_row="시공량", output_column={"column": "수량"},
        crew=["철공", "보통인부"], equipment=[], quantity_input="quantity",
        steps=["일당 시공량 7.8m로 길이 ÷ 7.8 = 작업일수를 구한다.", "작업일수 × 직종별 인원으로 총 투입량을 구한다.",
               "수직고 30m 초과(10m마다 9% 감)와 비탈경사 1:1.0 초과(43% 범위 내 가산)는 원문이 적용 방식을 정하지 않아 보류한다."],
        source="PDF 858쪽 1-1-3 표 및 비고", reason=GENERIC_REASON)


PIPE_CREW = ["배관공(수도)", "보통인부"]


@promotion("토목/6-6-1")
def socket_pipe(package: dict) -> None:
    spec = package["draft"]
    sizes = field(spec, "pipe_diameter")["allowed_values"]
    outputs = ("20", "15", "13", "11", "9.0", "8.0", "6.5", "5.5", "5.0", "5.0", "4.5", "4.0", "3.5", "3.5", "3.5", "3.0", "2.5")
    crew_by_size = [2] * 9 + [3] * 5 + [4] * 3  # 원문 표의 묶음: 250~800 / 900~1,350 / 1,500~2,000
    assert len(sizes) == len(outputs) == len(crew_by_size)
    retype(package, "p428-t0", {size: {"배관공(수도)": str(crew), "보통인부": "1", "양중장비": "1", "시공량(본)": out}
                                for size, crew, out in zip(sizes, crew_by_size, outputs)})
    simple_crew_table(
        package, table="p428-t0", output_row="pipe_diameter", output_column={"column": "시공량(본)"},
        crew=PIPE_CREW, equipment=[], quantity_input="quantity",
        steps=["관경 행의 일당 시공량(본)을 고른다.", "수량 ÷ 시공량으로 작업일수를 구한다.",
               "작업일수 × 직종별 인원(관경 묶음별 배관공 2/3/4인, 보통인부 1인), × 양중장비 1대로 총 투입량을 구한다."],
        source="PDF 6-6-1 표 및 [주]", reason=GENERIC_REASON,
        crew_column={"column_template": "{trade}", "row_input": "pipe_diameter"},
        extra={"equipment": [{"name": "양중장비", "table": "p428-t0", "row_selector": "pipe_diameter", "column": "양중장비",
                              "unit": "대·일"}]})


@promotion("토목/6-2-2")
def kp_mechanical_joint(package: dict) -> None:
    spec = package["draft"]
    big = ["125 이하", "150", "200", "250", "300", "350", "400", "450", "500", "600", "700", "800", "900", "1,000",
           "1,100~1,200"]
    outputs = ("17", "14", "11", "10", "8", "8.5", "7.5", "6.5", "6.0", "5.0", "5.0", "4.5", "4.0", "3.5", "3.0")
    crew_by_size = [2] * 5 + [3] * 5 + [4] * 5
    manual = {"80": ("3", "13"), "100": ("3", "12"), "120": ("4", "13"), "150": ("4", "9")}
    base = field(spec, "pipe_diameter")
    upsert_input(spec, {**base, "allowed_values": big, "when": {"input": "installation_method", "equals": "장비"}})
    upsert_input(spec, {**base, "name": "manual_pipe_diameter", "allowed_values": list(manual),
                        "when": {"input": "installation_method", "equals": "인력"},
                        "source": "PDF 6-2-2 비고(인력에 의한 부설 및 접합) 표"})
    retype(package, "p420-t2", {size: {"배관공(수도)": str(crew), "보통인부": "1", "양중장비": "1", "시공량(본)": out}
                                for size, crew, out in zip(big, crew_by_size, outputs)})
    retype(package, "p421-t1", {size: {"배관공(수도)": crew, "보통인부": "1", "시공량(본)": out}
                                for size, (crew, out) in manual.items()})
    spec["tables"] = [t for t in spec["tables"] if t["id"] != "p421-t0"]
    # 공구손료 요율은 관경 구간별(300㎜ 이하 4%, 350~600 3%, 700~1,200 2%): 입력 관경마다 해당 규칙을 둔다.
    chunk = chunk_for("6-2-2", "공구손료 및 경장비(임팩트렌치, 발전기 등)의 기계경비는 인력품에 다음 요율을 적용한다")
    quote = "공구손료 및 경장비(임팩트렌치, 발전기 등)의 기계경비는 인력품에 다음 요율을 적용한다"
    def rate(size: str) -> str:
        top = size.replace(",", "").split("~")[-1].replace(" 이하", "")
        value = int(top)
        return "0.04" if value <= 300 else "0.03" if value <= 600 else "0.02"
    spec["cost_rules"] = (
        [{"name": f"공구손료 및 경장비(관경 {size})", "category": "경비", "base": "labor_subtotal", "rate": rate(size),
          "when": {"pipe_diameter": size}, "cite": {"chunk_id": chunk, "quote": quote}} for size in big]
        + [{"name": f"공구손료 및 경장비(관경 {size})", "category": "경비", "base": "labor_subtotal", "rate": rate(size),
            "when": {"manual_pipe_diameter": size}, "cite": {"chunk_id": chunk, "quote": quote}} for size in manual])
    route = {"input": "installation_method", "values": {"장비": "p420-t2", "인력": "p421-t1"}}
    diameter = ["pipe_diameter", "manual_pipe_diameter"]
    finish(package, "daily_crew",
           "부설 방법(장비/인력)별 표에서 관경 행의 인원·양중장비·일당 시공량(본)을 읽는 일당 작업조 구조이며 "
           "공구손료 요율은 관경 구간별 조건부 비용 규칙으로 둔다. 이탈방지 압륜의 '30% 범위 내 가산'은 율이 정해져 있지 않아 보류한다.",
           ["부설 방법으로 표를 고르고 관경 행의 일당 시공량(본)을 읽는다.", "수량 ÷ 시공량으로 작업일수를 구한다.",
            "작업일수 × 직종별 인원, 장비 부설이면 × 양중장비 1대로 총 투입량을 구한다."],
           {"quantity_input": "quantity",
            "base_output": {"table_selector": route, "row_input": diameter, "column": "시공량(본)"},
            "coefficients": [],
            "crew": {"table_selector": route, "row_input": diameter, "column_template": "{trade}", "trades": PIPE_CREW,
                     "rate_codes": {n: "" for n in PIPE_CREW}},
            "equipment": [{"name": "양중장비", "table": "p420-t2", "row_selector": "pipe_diameter", "column": "양중장비",
                           "unit": "대·일", "when": {"installation_method": "장비"}}]},
           source="PDF 364~365쪽 6-2-2 표 및 [주]")


@promotion("건축/5-1-3")
def flooring_install(package: dict) -> None:
    retype(package, "p649-t4", {"내장공": {"수량": "2"}, "보통인부": {"수량": "1"}, "시공량": {"수량": "50"}})
    simple_crew_table(
        package, table="p649-t4", output_row="시공량", output_column={"column": "수량"},
        crew=["내장공", "보통인부"], equipment=[], quantity_input="volume", steps=GENERIC_STEPS,
        source="PDF 5-1-3 표", reason="표에 인원과 일당 시공량(㎡)이 함께 있는 일당 작업조 표라 단위당 품 계산이 아니라 일당 작업조로 표현한다.")


@promotion("유지관리/1-3-3")
def crack_packer_injection(package: dict) -> None:
    retype(package, "p924-t0", {"특별인부": {"수량": "3"}, "보통인부": {"수량": "1"}, "시공량": {"수량": "24"}})
    simple_crew_table(
        package, table="p924-t0", output_row="시공량", output_column={"column": "수량"},
        crew=["특별인부", "보통인부"], equipment=[], quantity_input="crack_length", steps=GENERIC_STEPS,
        source="PDF 1-3-3 표 및 [주]",
        reason="표에 인원과 일당 시공량(m)이 함께 있는 일당 작업조 표라 일당 작업조로 표현한다. 균열폭 10㎜ 초과는 원문이 적의 산출하라고 하여 보류한다.")


@promotion("공통/2-8-1")
def falling_object_net(package: dict) -> None:
    spec = package["draft"]
    spec["quantity_model"]["params"]["note_adjustments"] = []
    retype(package, "p106-t2", {"비계공": {"수량": "3"}, "보통인부": {"수량": "1"}, "시공량": {"수량": "100"}})
    materials = [("강관 ø48.6㎜×2.4㎜", "m", "2.70"), ("브라켓", "개", "0.26"), ("철선", "㎏", "0.25"),
                 ("클램프", "개", "0.27"), ("그물망", "㎡", "1.24")]
    retype(package, "p107-t0", {name: {"수량": qty} for name, _unit, qty in materials})
    simple_crew_table(
        package, table="p106-t2", output_row="시공량", output_column={"column": "수량"},
        crew=["비계공", "보통인부"], equipment=[], quantity_input="quantity",
        steps=GENERIC_STEPS + ["[참고자료]의 ㎡당 재료량을 면적에 곱한다(방진 손율 등은 미산정)."],
        source="PDF 2-8-1 표 및 [참고자료]", reason=GENERIC_REASON,
        extra={"materials": [{"name": name, "table": "p107-t0", "row": name, "unit": unit}
                             for name, unit, _qty in materials]})


def declare_quantity_column(package: dict, table: str) -> None:
    """초안이 표의 '수량' 열을 인원·장비 대수 열로 지정하지 않아 계산이 열을 고르지 못하던 절."""
    params = package["draft"]["quantity_model"]["params"]
    assert params["crew"]["table"] == table
    params["crew"]["column"] = "수량"
    for item in params.get("equipment", []):
        if item.get("table") == table:
            item["column"] = "수량"
    package["calc_type_reason"] = ("인원·장비 대수가 표의 '수량' 열에 있어 열 지정만 보완하면 기존 일당 작업조 계산기로 표현된다.")


@promotion("건축/8-2-2")
def anchored_railing(package: dict) -> None:
    declare_quantity_column(package, "p675-t2")


@promotion("유지관리/2-4-11")
def sump_dredging(package: dict) -> None:
    declare_quantity_column(package, "p964-t0")


@promotion("토목/1-7-4")
def porous_asphalt_small(package: dict) -> None:
    declare_quantity_column(package, "p375-t2")


@promotion("토목/6-5-2")
def band_joint(package: dict) -> None:
    spec = package["draft"]
    sizes = field(spec, "pipe_diameter")["allowed_values"]
    outputs = ("22", "16", "13", "11", "10", "8.5", "7.5", "7.0", "6.0")
    retype(package, "p426-t1", {size: {"배관공(수도)": "2", "보통인부": "1", "시공량(개소)": out}
                                for size, out in zip(sizes, outputs)})
    simple_crew_table(
        package, table="p426-t1", output_row="pipe_diameter", output_column={"column": "시공량(개소)"},
        crew=PIPE_CREW, equipment=[], quantity_input="quantity", steps=GENERIC_STEPS, source="PDF 6-5-2 표 및 [주]",
        reason=GENERIC_REASON, crew_column={"column_template": "{trade}", "row_input": "pipe_diameter"})


@promotion("토목/6-6-2")
def watertight_band_joint(package: dict) -> None:
    spec = package["draft"]
    sizes = field(spec, "pipe_diameter")["allowed_values"]
    outputs = ("21", "16", "13", "11", "10", "9", "7", "6", "5", "5", "4", "3.5", "3.5", "3", "2.5")
    crew_by_size = [2] * 9 + [3] * 3 + [4] * 3  # 원문 표의 묶음: 250~800 / 900~1,350 / 1,500~2,000
    assert len(sizes) == len(outputs) == len(crew_by_size)
    retype(package, "p429-t0", {size: {"배관공(수도)": str(crew), "보통인부": "1", "양중장비": "1", "시공량(본)": out}
                                for size, crew, out in zip(sizes, crew_by_size, outputs)})
    simple_crew_table(
        package, table="p429-t0", output_row="pipe_diameter", output_column={"column": "시공량(본)"},
        crew=PIPE_CREW, equipment=[], quantity_input="quantity", steps=GENERIC_STEPS, source="PDF 6-6-2 표 및 [주]",
        reason=GENERIC_REASON, crew_column={"column_template": "{trade}", "row_input": "pipe_diameter"},
        extra={"equipment": [{"name": "양중장비", "table": "p429-t0", "row_selector": "pipe_diameter", "column": "양중장비",
                              "unit": "대·일"}]})


@promotion("기계설비/1-4-1")
def mechanical_joint_piping(package: dict) -> None:
    spec = package["draft"]
    sizes = field(spec, "pipe_size")["allowed_values"]
    outputs = ("18", "14", "13", "10", "8.5", "7.5", "6.0")
    retype(package, "p710-t0", {size: {"배관공": "3", "보통인부": "1", "시공량(접합개소)": out}
                                for size, out in zip(sizes, outputs)})
    lift = field(spec, "work_method")["allowed_values"][1]
    spec["cost_rules"] = [{**rule, "when": {"work_method": value}}
                          for rule, value in zip(spec["cost_rules"], field(spec, "work_method")["allowed_values"])]
    simple_crew_table(
        package, table="p710-t0", output_row="pipe_size", output_column={"column": "시공량(접합개소)"},
        crew=["배관공", "보통인부"], equipment=[], quantity_input="quantity",
        steps=["관규격 행의 일당 시공량(접합개소)을 고른다.", "자체 추진 고소작업대(시저형) 시공이면 시공량의 26%를 가산한다.",
               "접합개소 ÷ 시공량으로 작업일수를 구하고 인원을 곱한다. 공구손료는 인력시공 2%, 고소작업대 시공 10%."],
        source="PDF 1-4-1 표 및 비고", reason=GENERIC_REASON + " 비고의 26% 가산을 출력 보정으로 표현한다.",
        crew_column={"column_template": "{trade}", "row_input": "pipe_size"},
        extra={"output_adjustments": [{
            "when": {"work_method": lift}, "operation": "multiply_output", "value": "63/50",
            "source": "비고: 자체 추진 고소작업대(시저형)시공의 경우 시공량의 26%를 가산한다",
            "cite": {"table_id": "p710-t0"}}]})


@promotion("공통/6-6-1")
def bridge_bearing_land(package: dict) -> None:
    spec = package["draft"]
    weights = field(spec, "weight")["allowed_values"]
    heights = field(spec, "height")["allowed_values"]
    blocks = [(2, ("8.5", "7.0", "5.5")), (2, ("6.0", "5.0", "4.0")), (3, ("5.0", "4.0", "3.5")),
              (3, ("4.0", "3.5", "3.0")), (4, ("3.5", "3.0", "2.5")), (4, ("3.0", "2.5", "2.0"))]
    assert len(weights) == len(blocks) and len(heights) == 3
    retype(package, "p206-t1", {
        weight: {"특별인부": str(special), "보통인부": "1", "용접공": "1", "크레인": "1", "고소작업차": "1",
                 **dict(zip(heights, outputs))}
        for weight, (special, outputs) in zip(weights, blocks)})
    spec["tables"] = [t for t in spec["tables"] if t["id"] != "p207-t0"]
    crew = ["특별인부", "보통인부", "용접공"]
    finish(package, "daily_crew",
           "교량받침 중량 블록별 인원·장비 대수와 설치높이별 일당 시공량이 반복되는 정규 구조라 기존 일당 작업조 계산기로 표현된다.",
           ["중량 블록과 설치높이로 일당 시공량(개)을 고른다.", "설치 수량 ÷ 일당 시공량으로 작업일수를 구한다.",
            "작업일수 × 해당 중량 블록의 직종별 인원, × 장비 대수(크레인·고소작업차)로 총 투입량을 구한다."],
           {"quantity_input": "quantity",
            "base_output": {"table": "p206-t1", "row_input": "weight", "column_input": "height"},
            "coefficients": [],
            "crew": {"table": "p206-t1", "row_input": "weight", "column_template": "{trade}", "trades": crew,
                     "rate_codes": {n: "" for n in crew}},
            "equipment": [{"name": name, "table": "p206-t1", "row_selector": "weight", "column": name, "unit": "대·일"}
                          for name in ("크레인", "고소작업차")]},
           source="PDF 150~151쪽 6-6-1 표 및 [주]")
    refresh_table_citations(package, "p206-t1")


@promotion("토목/6-3-2")
def steel_pipe_welding(package: dict) -> None:
    spec = package["draft"]
    sizes = field(spec, "pipe_diameter")["allowed_values"]
    kinds = field(spec, "weld_type")["allowed_values"]  # A종 겹치기 / A종 베벨엔드 / B종 겹치기
    rows = [("11.0", "10.0", "-"), ("10.0", "9.0", "-"), ("9.0", "8.5", "-"), ("7.5", "7.0", "-"), ("6.5", "6.0", "-"),
            ("5.5", "5.0", "-"), ("9.5", "8.5", "-"), ("8.0", "7.0", "-"), ("6.5", "6.0", "-"), ("5.0", "4.5", "-"),
            ("3.5", "3.0", "-"), ("2.5", "-", "4.0"), ("2.0", "-", "3.0"), ("1.5", "-", "2.5"), ("1.5", "-", "2.0"),
            ("1.0", "-", "2.0"), ("1.0", "-", "1.5"), ("1.0", "-", "1.5"), ("1.0", "-", "1.5"), ("1.0", "-", "1.5"),
            ("1.0", "-", "1.0")]
    crew_by_size = [1] * 6 + [2] * 5 + [3] * 7 + [4] * 3  # 350 이하 1 / 400~700 2 / 800~1,500~1,650 3 / 1,800~2,400 4
    assert len(sizes) == len(rows) == len(crew_by_size)
    retype(package, "p423-t0", {size: {"용접공": str(crew), **dict(zip(kinds, cells))}
                                for size, crew, cells in zip(sizes, crew_by_size, rows)})
    # 원문 '-'는 그 관경에 해당 용접 종류의 품이 없다는 뜻이다. 0이 아니라 계산하지 않는 조합으로 보류한다.
    spec["blocked"] = [
        {"condition": f"관경 {size} · {kind}: 원문 표에 시공량이 없음('-')",
         "blocked_if_all": [{"input": "pipe_diameter", "op": "==", "value": size},
                            {"input": "weld_type", "op": "==", "value": kind}],
         "reason": "원문 표는 이 관경·용접 종류 조합에 시공량을 두지 않는다('-').", "source": "PDF 6-3-2 표",
         "cite": {"table_id": "p423-t0"}}
        for size, cells in zip(sizes, rows) for kind, cell in zip(kinds, cells) if cell == "-"]
    finish(package, "daily_crew",
           "관경 행의 용접공 인원과 용접 종류 열의 일당 시공량이 표에 있어 일당 작업조 계산기로 표현된다. "
           "원문 '-' 칸은 0이 아니라 해당 조합 없음으로 보류한다.",
           ["관경과 용접 종류로 일당 시공량(개소)을 고른다(표에 '-'이면 적용 불가).", "개소 ÷ 시공량으로 작업일수를 구한다.",
            "작업일수 × 용접공 인원(관경별 1/2/3/4인)으로 총 투입량을 구한다."],
           {"quantity_input": "quantity",
            "base_output": {"table": "p423-t0", "row_input": "pipe_diameter", "column_input": "weld_type"},
            "coefficients": [],
            "crew": {"table": "p423-t0", "row_input": "pipe_diameter", "column_template": "{trade}",
                     "trades": ["용접공"], "rate_codes": {"용접공": ""}}},
           source="PDF 367쪽 6-3-2 표 및 [주]")


def transposed_crew_row(package: dict, table: str, count_row: str = "수량") -> None:
    """인원 대수가 '수량' 행(열=직종)에 놓인 표: 직종을 열로 읽는다."""
    params = package["draft"]["quantity_model"]["params"]
    crew = params["crew"]
    assert crew["table"] == table
    crew.pop("column", None)
    crew["row_selector"] = count_row
    crew["column_template"] = "{trade}"
    for item in params.get("equipment", []) if isinstance(params.get("equipment"), list) else []:
        if item.get("table") == table:
            item["row"] = count_row
            item["column"] = item["name"]
    package["calc_type_reason"] = "인원 대수가 '수량' 행에 직종별 열로 있어 열 지정만 보완하면 기존 일당 작업조 계산기로 표현된다."


@promotion("공통/6-2-2")
def rebar_fabrication(package: dict) -> None:
    transposed_crew_row(package, "p189-t2")


@promotion("공통/6-7-1")
def flume_pipe(package: dict) -> None:
    spec = package["draft"]
    spec["inputs"] = [i for i in spec["inputs"] if i["name"] != "excavator_spec"]  # 선택지가 하나뿐인 질문
    params = spec["quantity_model"]["params"]
    params["equipment"] = [{"name": "굴착기", "table": "p211-t2", "unit": "대·일"}]
    transposed_crew_row(package, "p211-t2")


@promotion("건축/8-2-4")
def light_ceiling_frame(package: dict) -> None:
    spec = package["draft"]
    transposed_crew_row(package, "p676-t1")
    # 비고: 톱니형 달대볼트로 시공할 경우 시공량의 41%를 가산한다(블록이 아니라 출력 보정).
    spec["blocked"] = [b for b in spec["blocked"] if "톱니형" not in b["condition"]]
    spec["quantity_model"]["params"]["output_adjustments"] = [{
        "when": {"bolt_type": "톱니형 달대볼트"}, "operation": "multiply_output", "value": "141/100",
        "source": "비고: 톱니형 달대볼트로 시공할 경우에는 시공량의 41%를 가산한다", "cite": {"table_id": "p676-t1"}}]


@promotion("기계설비/2-1-1")
def galvanized_duct(package: dict) -> None:
    spec = package["draft"]
    sizes = field(spec, "thickness")["allowed_values"]
    outputs = ("18", "20", "18", "15", "13", "10")
    retype(package, "p715-t0", {size: {"덕트공": "3", "보통인부": "1", "시공량(㎡)": out}
                                for size, out in zip(sizes, outputs)})
    methods = field(spec, "work_method")["allowed_values"]
    needle = "공구손료 및 경장비(드릴,자체 추진 고소작업대(시저형) 등)의 기계경비는 다음 요율을 적용한다"
    chunk = chunk_for("2-1-1", needle, "기계설비")
    spec["blocked"] = []
    spec["cost_rules"] = [
        {"name": f"공구손료 및 경장비({method})", "category": "경비", "base": "labor_subtotal", "rate": rate,
         "when": {"work_method": method}, "cite": {"chunk_id": chunk, "quote": needle}}
        for method, rate in zip(methods, ("0.02", "0.10"))]
    simple_crew_table(
        package, table="p715-t0", output_row="thickness", output_column={"column": "시공량(㎡)"},
        crew=["덕트공", "보통인부"], equipment=[], quantity_input="quantity",
        steps=["호칭두께 행의 일당 시공량(㎡)을 고른다.", "자체 추진 고소작업대(시저형) 시공이면 시공량의 13%를 가산한다.",
               "면적 ÷ 시공량으로 작업일수를 구하고 인원을 곱한다. 공구손료는 인력시공 2%, 고소작업대 시공 10%."],
        source="PDF 2-1-1 표 및 비고", reason=GENERIC_REASON + " 비고의 13% 가산을 출력 보정으로 표현한다.",
        crew_column={"column_template": "{trade}", "row_input": "thickness"},
        extra={"output_adjustments": [{
            "when": {"work_method": methods[1]}, "operation": "multiply_output", "value": "113/100",
            "source": "비고: 자체 추진 고소작업대(시저형) 시공의 경우 시공량의 13%를 가산한다",
            "cite": {"table_id": "p715-t0"}}]})


@promotion("토목/1-6-2")
def surface_manual_paving(package: dict) -> None:
    transposed_crew_row(package, "p371-t1")


@promotion("공통/5-2-1")
def mat_laying(package: dict) -> None:
    spec = package["draft"]
    upsert_input(spec, {**field(spec, "depth_over_10m"), "when": {"input": "condition", "equals": "수중"},
                        "ask": "수중 부설의 수심이 10m를 초과합니까?"})
    spec["blocked"] = [b for b in spec["blocked"] if b.get("blocked_if")] + [{
        "condition": "수중 연약지반(매립지)", "blocked_if_all": [
            {"input": "condition", "op": "==", "value": "수중"},
            {"input": "site_type", "op": "==", "value": "연약지반(매립지)"}],
        "reason": "원문 표에는 수중 부설의 연약지반(매립지) 시공량이 없다.", "source": "PDF 5-2-1 표",
        "cite": {"table_id": "p165-t2"}}]
    retype(package, "p165-t2", {
        "특별인부": {"육상": "3", "수중": "2"}, "보통인부": {"육상": "1", "수중": "1"},
        "굴착기 0.4㎥": {"육상": "1"}, "잠수조": {"수중": "1"},
        "사면": {"육상": "4800", "수중": "1150"}, "연약지반(도로/철도)": {"육상": "3600", "수중": "700"},
        "연약지반(매립지)": {"육상": "3200"}})
    crew = ["특별인부", "보통인부"]
    finish(package, "daily_crew",
           "육상/수중과 시공 위치별 인원·장비·일당 시공량이 표에 있어 일당 작업조 계산기로 표현된다. 원문에 없는 "
           "수중 연약지반(매립지) 조합은 막는다.",
           ["시공 위치(행)와 육상/수중(열)의 일당 시공량(㎡)을 고른다.", "면적 ÷ 시공량으로 작업일수를 구한다.",
            "작업일수 × 직종별 인원, 육상은 굴착기 1대, 수중은 잠수조 1조를 곱한다."],
           {"quantity_input": "quantity",
            "base_output": {"table": "p165-t2", "row_input": "site_type", "column_input": "condition"},
            "coefficients": [],
            "crew": {"table": "p165-t2", "column_input": "condition", "trades": crew,
                     "rate_codes": {n: "" for n in crew}},
            "equipment": [{"name": "굴착기 0.4㎥", "table": "p165-t2", "column": "육상", "unit": "대·일",
                           "when": {"condition": "육상"}},
                          {"name": "잠수조", "table": "p165-t2", "column": "수중", "unit": "조·일",
                           "when": {"condition": "수중"}}]},
           source="PDF 109쪽 5-2-1 표 및 [주]")
    refresh_table_citations(package, "p165-t2")


def tree_work_by_method(package: dict, *, table: str, cond_input: str, band_input: str, rows: dict, section: str,
                        lift: bool) -> None:
    """수목 작업(인력/기계 × 낙엽수/상록수 × 흉고직경 구간). 원문 '-' 칸은 해당 조합 없음으로 막는다."""
    spec = package["draft"]
    conditions = field(spec, cond_input)["allowed_values"]
    bands = field(spec, band_input)["allowed_values"]
    values = {"조경공": {"수량": "2"}, "보통인부": {"수량": "1"}, **({"고소작업차": {"수량": "1"}} if lift else {})}
    for condition, cells in zip(conditions, rows):
        assert len(cells) == len(bands)
        values[condition] = dict(zip(bands, cells))
    retype(package, table, values)
    spec["inputs"] = [i for i in spec["inputs"] if i["name"] != "aerial_lift_spec"]  # 선택지가 하나뿐인 질문
    spec["blocked"] = [
        {"condition": f"{condition} · {band}: 원문 표에 시공량이 없음('-')",
         "blocked_if_all": [{"input": cond_input, "op": "==", "value": condition},
                            {"input": band_input, "op": "==", "value": band}],
         "reason": "원문 표는 이 시공 방법·수종·흉고직경 조합에 시공량을 두지 않는다('-').",
         "source": f"PDF {section} 표", "cite": {"table_id": table}}
        for condition, cells in zip(conditions, rows) for band, cell in zip(bands, cells) if cell == "-"]
    equipment = ([{"name": "고소작업차", "table": table, "column": "수량", "unit": "대·일", "when": {cond_input: c}}
                  for c in conditions if c.startswith("기계")] if lift else [])
    simple_crew_table(
        package, table=table, output_row=cond_input, output_column={"column_input": band_input},
        crew=["조경공", "보통인부"], equipment=[], quantity_input="quantity",
        steps=["시공 방법·수종과 흉고직경 구간의 일당 시공량(주)을 고른다(표에 '-'이면 적용 불가).",
               "수량 ÷ 시공량으로 작업일수를 구한다.", "작업일수 × 직종별 인원(기계 시공은 고소작업차 1대)으로 총 투입량을 구한다."],
        source=f"PDF {section} 표 및 [주]", reason=GENERIC_REASON + " 원문 '-' 칸은 0이 아니라 해당 조합 없음으로 막는다.",
        extra={"equipment": equipment})


@promotion("유지관리/1-2-2")
def general_pruning(package: dict) -> None:
    tree_work_by_method(
        package, table="p915-t0", cond_input="work_condition", band_input="dbm_size", section="859쪽 1-2-2", lift=True,
        rows=[("36", "22", "13", "-", "-", "-", "-"), ("42", "24", "15", "-", "-", "-", "-"),
              ("-", "48", "31", "18", "13", "8", "6"), ("-", "56", "35", "22", "15", "10", "7")])


@promotion("유지관리/1-2-3")
def shaped_pruning(package: dict) -> None:
    tree_work_by_method(
        package, table="p916-t0", cond_input="work_type", band_input="diameter", section="860쪽 1-2-3", lift=True,
        rows=[("23", "14", "8", "-", "-", "-", "-"), ("27", "16", "10", "-", "-", "-", "-"),
              ("-", "31", "20", "12", "8", "5", "4"), ("-", "36", "23", "14", "10", "7", "5")])


@promotion("유지관리/1-2-6")
def trunk_protection(package: dict) -> None:
    spec = package["draft"]
    bands = field(spec, "diameter")["allowed_values"]
    retype(package, "p917-t2", {"조경공": {"수량": "2"}, "보통인부": {"수량": "1"},
                                "수간보호 (조형)": dict(zip(bands, ("24", "13", "6", "3", "2"))),
                                "수간보호 (일반)": dict(zip(bands, ("38", "24", "16", "11", "8")))})
    simple_crew_table(
        package, table="p917-t2", output_row="work_type", output_column={"column_input": "diameter"},
        crew=["조경공", "보통인부"], equipment=[], quantity_input="quantity", steps=GENERIC_STEPS,
        source="PDF 861쪽 1-2-6 표 및 [주]", reason=GENERIC_REASON + " 흉고직경 51cm 이상은 원문 표에 없어 보류한다.")


@promotion("유지관리/2-1-32")
def curb_removal(package: dict) -> None:
    spec = package["draft"]
    sizes = field(spec, "size")["allowed_values"]
    types = field(spec, "type")["allowed_values"]
    outputs = {"A-Type": ("500", "420", "390", "270", "170"), "B-Type": ("400", "335", "310", "215", "130")}
    values = {"특별인부": {"A-Type": "2", "B-Type": "2"}, "보통인부": {"A-Type": "1", "B-Type": "1"},
              "굴착기 0.4㎥": {"A-Type": "1"}, "굴착기 0.2㎥": {"B-Type": "1"},
              "트럭 2.5ton": {"A-Type": "1", "B-Type": "1"}}
    for index, size in enumerate(sizes):
        values[size] = {kind: outputs[kind][index] for kind in types}
    retype(package, "p948-t0", values)
    crew = ["특별인부", "보통인부"]
    finish(package, "daily_crew",
           "Type별 인원·장비 대수와 규격별 일당 시공량이 표에 있어 기존 일당 작업조 계산기로 표현된다.",
           ["Type와 경계블록 규격(아래폭+높이)의 일당 시공량(m)을 고른다.", "철거 물량 ÷ 시공량으로 작업일수를 구한다.",
            "Type별 직종 인원·굴착기·트럭 대수를 작업일수에 곱한다."],
           {"quantity_input": "quantity",
            "base_output": {"table": "p948-t0", "row_input": "size", "column_input": "type"},
            "coefficients": [],
            "crew": {"table": "p948-t0", "column_input": "type", "trades": crew, "rate_codes": {n: "" for n in crew}},
            "equipment": [{"name": "굴착기 0.4㎥", "table": "p948-t0", "column": "A-Type", "unit": "대·일",
                           "when": {"type": "A-Type"}},
                          {"name": "굴착기 0.2㎥", "table": "p948-t0", "column": "B-Type", "unit": "대·일",
                           "when": {"type": "B-Type"}},
                          {"name": "트럭 2.5ton", "table": "p948-t0", "column_input": "type", "unit": "대·일"}]},
           source="PDF 892쪽 2-1-32 표 및 [주]")


@promotion("유지관리/2-1-18")
def surface_leveling(package: dict) -> None:
    retype(package, "p941-t2", {
        "작업반장": {"수량": "1"}, "보통인부": {"수량": "1"}, "그라인딩 장비 W=1.25m": {"수량": "1"},
        "로더(타이어) 0.57㎥": {"수량": "1"}, "살수차 5,500ℓ": {"수량": "1"}, "시공량": {"수량": "1100"}})
    simple_crew_table(
        package, table="p941-t2", output_row="시공량", output_column={"column": "수량"},
        crew=["작업반장", "보통인부"], equipment=["그라인딩 장비 W=1.25m", "로더(타이어) 0.57㎥", "살수차 5,500ℓ"],
        quantity_input="quantity",
        steps=["일당 시공량 1,100㎡로 면적 ÷ 시공량 = 작업일수를 구한다.", "작업일수 × 직종별 인원, × 사용기계 1대씩으로 총 투입량을 구한다.",
               "작업면적 10㎡ 이하·분산 소규모는 일당시공량의 30% 범위 내 감산이라 율이 정해져 있지 않아 보류한다."],
        source="PDF 2-1-18 표 및 [주]", reason=GENERIC_REASON)


@promotion("공통/6-6-7")
def precast_panel(package: dict) -> None:
    crew = ["특별인부", "보통인부", "콘크리트공"]
    equipment = [{"name": "이동용대차+크레인", "table": "p210-t1", "column": "대차시공", "unit": "대·일",
                  "when": {"construction_method": "대차시공"}},
                 {"name": "크레인", "table": "p210-t1", "column": "크레인시공", "unit": "대·일",
                  "when": {"construction_method": "크레인시공"}},
                 {"name": "지게차 5ton", "table": "p210-t1", "column_input": "construction_method", "unit": "대·일"}]
    retype(package, "p210-t1", {
        "특별인부": {"대차시공": "4", "크레인시공": "4"}, "보통인부": {"대차시공": "1", "크레인시공": "1"},
        "콘크리트공": {"대차시공": "1", "크레인시공": "1"}, "이동용대차+크레인": {"대차시공": "1"},
        "크레인": {"크레인시공": "1"}, "지게차 5ton": {"대차시공": "1", "크레인시공": "1"},
        "시공량": {"대차시공": "85", "크레인시공": "70"}})
    finish(package, "daily_crew",
           "시공 방식(대차/크레인)별 인원·장비·일당 시공량이 표에 있어 기존 일당 작업조 계산기로 표현된다.",
           ["시공 방식 열의 일당 시공량(㎡)을 고른다.", "면적 ÷ 시공량으로 작업일수를 구한다.",
            "작업일수 × 직종별 인원, × 해당 방식의 장비(이동용대차+크레인 또는 크레인, 지게차) 대수로 총 투입량을 구한다."],
           {"quantity_input": "quantity",
            "base_output": {"table": "p210-t1", "row": "시공량", "column_input": "construction_method"},
            "coefficients": [],
            "crew": {"table": "p210-t1", "column_input": "construction_method", "trades": crew,
                     "rate_codes": {n: "" for n in crew}},
            "equipment": equipment},
           source="PDF 154~155쪽 6-6-7 표 및 [주]")


@promotion("토목/5-2-4")
def steel_bridge_painting(package: dict) -> None:
    spec = package["draft"]
    retype(package, "p416-t0", {"도장공": {"공장도장": "1", "현장도장": "1"}, "특별인부": {"공장도장": "1", "현장도장": "1"},
                                "도장면적": {"공장도장": "100", "현장도장": "60"}})
    spec["blocked"] = [{
        "condition": "도장 횟수가 1회를 넘는 경우", "blocked_if": {"input": "paint_count", "op": ">", "value": "1"},
        "reason": "본 품은 도장횟수 1회 기준이며 횟수가 늘 때 적용 방법은 원문에 없다.", "source": "PDF 5-2-4 [주] ①",
        "cite": {"table_id": "p416-t0"}}]
    spec["cost_rules"] = [{**spec["cost_rules"][0], "when": {"paint_location": "현장도장"}}]
    simple_crew_table(
        package, table="p416-t0", output_row="도장면적", output_column={"column_input": "paint_location"},
        crew=["도장공", "특별인부"], equipment=[], quantity_input="area",
        steps=["도장 장소(공장/현장)의 일당 도장면적(㎡)을 고른다.", "박스거더 내면 도장이면 일당시공량을 33% 감한다.",
               "면적 ÷ 시공량으로 작업일수를 구하고 인원을 곱한다. 현장도장은 인력품의 5%를 공구손료로 둔다."],
        source="PDF 5-2-4 표 및 [주]", reason=GENERIC_REASON + " 박스거더 내면 도장 33% 감을 출력 보정으로 표현한다.",
        crew_column={"column_input": "paint_location"},
        extra={"output_adjustments": [{
            "when": {"is_inner_box": True}, "operation": "set_output_percent", "value": "33",
            "source": "[주] ③ 박스거더 내면 도장과 같은 내면 도장의 경우 일당시공량(도장면적)을 33% 할감하여 적용한다",
            "cite": {"table_id": "p416-t0"}}]})


def planting_family(package: dict, *, table: str, method_input: str, band_input: str, quantity: str, groups: list,
                    section: str, adjustments: list, equipment_names: list[str]) -> None:
    """식재·굴취: 시공 방법(인력/기계)과 크기 구간마다 작업조·장비가 달라지는 표.

    groups: [(방법, [구간…], [시공량…], {직종/장비: 수량…})]. 원문 표에 없는 (방법, 구간) 조합은 막는다.
    표에 해당 작업조에 없는 장비는 0이 아니라 '장비 없음'이므로 결과에서 빼 둔다(omit_if_zero).
    """
    spec = package["draft"]
    methods = field(spec, method_input)["allowed_values"]
    bands = field(spec, band_input)["allowed_values"]
    values, listed = {}, set()
    for method, group_bands, outputs, crew in groups:
        assert method in methods and len(group_bands) == len(outputs)
        for band, output in zip(group_bands, outputs):
            assert band in bands, band
            values[f"{method}|{band}"] = {**{name: "0" for name in equipment_names}, **crew, "시공량": output}
            listed.add((method, band))
    retype(package, table, values)
    spec["blocked"] = [b for b in spec["blocked"] if b.get("blocked_if")] + [
        {"condition": f"{method} · {band}: 원문 표에 시공량이 없음",
         "blocked_if_all": [{"input": method_input, "op": "==", "value": method},
                            {"input": band_input, "op": "==", "value": band}],
         "reason": "원문 표는 이 시공 방법·크기 구간 조합에 시공량을 두지 않는다.", "source": f"PDF {section} 표",
         "cite": {"table_id": table}}
        for method in methods for band in bands if (method, band) not in listed]
    row = {"input": method_input, "contains": ["{value}"], "exact_input_contains": [band_input]}
    crew = ["조경공", "보통인부"]
    finish(package, "daily_crew",
           "시공 방법과 크기 구간별 작업조·장비·일당 시공량이 표에 있어 행 선택자로 표현되는 일당 작업조 구조다. "
           "원문 표에 없는 조합은 막는다.",
           ["시공 방법과 크기 구간의 일당 시공량(주)을 고른다.", "수량 ÷ 시공량으로 작업일수를 구한다.",
            "작업일수 × 직종별 인원, × 해당 작업조의 장비 대수로 총 투입량을 구한다."],
           {"quantity_input": quantity,
            "base_output": {"table": table, "row_selector": row, "column": "시공량"},
            "coefficients": [],
            "crew": {"table": table, "row_selector": row, "column_template": "{trade}", "trades": crew,
                     "rate_codes": {n: "" for n in crew}},
            "equipment": [{"name": name, "table": table, "row_selector": row, "column": name, "unit": "대·일",
                           "omit_if_zero": True} for name in equipment_names],
            "output_adjustments": adjustments},
           source=f"PDF {section} 표 및 비고")


@promotion("공통/4-3-4")
def planting_by_height(package: dict) -> None:
    heights = field(package["draft"], "tree_height")["allowed_values"]
    planting_family(
        package, table="p152-t0", method_input="method", band_input="tree_height", quantity="quantity",
        section="152쪽 4-3-4", equipment_names=["굴착기 0.4㎥"],
        groups=[("인력시공", heights, ("40", "20", "12"), {"조경공": "4", "보통인부": "2"}),
                ("기계시공", heights, ("55", "30", "20"), {"조경공": "3", "보통인부": "1", "굴착기 0.4㎥": "1"})],
        adjustments=[{"when": {"support_prop": False}, "operation": "multiply_output", "value": "111/100",
                      "source": "비고: 지주목을 세우지 않을 때는 시공량의 11%를 가산한다", "cite": {"table_id": "p152-t0"}}])


@promotion("공통/4-3-5")
def planting_by_diameter(package: dict) -> None:
    bands = field(package["draft"], "tree_diameter")["allowed_values"]
    planting_family(
        package, table="p152-t1", method_input="construction_method", band_input="tree_diameter",
        quantity="quantity", section="152쪽 4-3-5", equipment_names=["굴착기 0.4㎥", "굴착기 0.6㎥", "크레인"],
        groups=[("인력시공", bands[:2], ("30", "15"), {"조경공": "4", "보통인부": "2"}),
                ("기계시공", bands[:4], ("45", "22", "17", "12"),
                 {"조경공": "3", "보통인부": "1", "굴착기 0.4㎥": "1"}),
                ("기계시공", bands[4:], ("9", "7", "5", "4"),
                 {"조경공": "3", "보통인부": "1", "굴착기 0.6㎥": "1", "크레인": "1"})],
        adjustments=[{"when": {"support_prop_used": False}, "operation": "multiply_output", "value": "111/100",
                      "source": "비고: 지주목을 세우지 않을 때는 시공량의 11%를 가산한다", "cite": {"table_id": "p152-t1"}}])


@promotion("공통/4-3-3")
def tree_digging(package: dict) -> None:
    bands = field(package["draft"], "diameter")["allowed_values"]
    planting_family(
        package, table="p151-t1", method_input="method", band_input="diameter", quantity="quantity",
        section="151쪽 4-3-3", equipment_names=["굴착기 0.4㎥", "굴착기 0.6㎥", "크레인"],
        groups=[("인력시공", bands[:3], ("50", "30", "15"), {"조경공": "4", "보통인부": "2"}),
                ("기계시공", bands[:5], ("70", "40", "25", "15", "10"),
                 {"조경공": "3", "보통인부": "1", "굴착기 0.4㎥": "1"}),
                ("기계시공", bands[5:], ("7", "5", "4", "3"),
                 {"조경공": "3", "보통인부": "1", "굴착기 0.6㎥": "1", "크레인": "1"})],
        adjustments=[{"when": {"has_root_ball": False}, "operation": "multiply_output", "value": "5/4",
                      "source": "비고: 분이 없는 경우 시공량의 25%를 가산한다", "cite": {"table_id": "p151-t1"}}])


@promotion("공통/4-2-2")
def shrub_planting(package: dict) -> None:
    spec = package["draft"]
    bands = field(spec, "effective_height_band")["allowed_values"][:4]
    retype(package, "p149-t1", {"조경공": {"수량": "3"}, "보통인부": {"수량": "1"},
                                "시공량": dict(zip(bands, ("160", "125", "75", "55")))})
    simple_crew_table(
        package, table="p149-t1", output_row="시공량", output_column={"column_input": "effective_height_band"},
        crew=["조경공", "보통인부"], equipment=[], quantity_input="quantity", steps=GENERIC_STEPS,
        source="PDF 93쪽 4-2-2 표 및 [주]", reason=GENERIC_REASON + " 나무높이 1.5m 초과·특수식재는 원문이 별도/비례 감산이라 보류한다.",
        crew_column={"column": "수량"})


def indoor_pipe_family(package: dict, *, table: str, rate_table: str, sizes_input: str, lift_input: str,
                       location_input: str, outputs: tuple, crew_by_size: list[int], output_unit_row: str,
                       cost_chunk: str, section: str) -> None:
    """옥내 일반배관 품(기계설비 1-x): 관규격별 시공량(m), 시공위치별 증감 요율, 고소작업대(시저형) 26% 가산, 공구손료 2%/10%.
    고소작업대 가산과 시공위치 요율이 함께 적용될 때의 결합 방식은 원문에 없어 그 조합은 보류한다."""
    spec = package["draft"]
    sizes = field(spec, sizes_input)["allowed_values"]
    locations = field(spec, location_input)["allowed_values"]
    assert len(sizes) == len(outputs) == len(crew_by_size)
    retype(package, table, {size: {"배관공": str(crew), "보통인부": "1", output_unit_row: out}
                            for size, crew, out in zip(sizes, crew_by_size, outputs)})
    adjustments = []
    for place, percent, source in zip(locations[1:], ("17", "23", "11"), ("-17%", "-23%", "+11%")):
        value = "111/100" if source.startswith("+") else None
        adjustments.append({"when": {location_input: place, lift_input: False},
                            **({"operation": "multiply_output", "value": value} if value else
                               {"operation": "set_output_percent", "value": percent}),
                            "source": f"비고: 시공위치 {place} 시공량 요율 {source}", "cite": {"table_id": rate_table}})
    adjustments.append({"when": {lift_input: True, location_input: locations[0]}, "operation": "multiply_output",
                        "value": "63/50", "source": "비고: 자체 추진 고소작업대(시저형)시공의 경우 시공량의 26%를 가산한다",
                        "cite": {"table_id": table}})
    blocked = [b for b in spec["blocked"] if "인서트" in b["condition"]]
    blocked += [{"condition": f"고소작업대 가산과 시공위치({place}) 요율이 함께 적용되는 경우",
                 "blocked_if_all": [{"input": lift_input, "op": "==", "value": True},
                                    {"input": location_input, "op": "==", "value": place}],
                 "reason": "두 증감 요율이 함께 적용될 때 결합 방식(합산/곱)이 원문에 명시되어 있지 않다.",
                 "source": f"PDF {section} 비고", "cite": {"table_id": rate_table}} for place in locations[1:]]
    spec["blocked"] = blocked
    quote = "공구손료 및 경장비(절단기, 자체 추진 고소작업대(시저형) 등)의 기계경비는 인력품의 2%(인력시공)"
    spec["cost_rules"] = [
        {"name": "공구손료 및 경장비(인력시공)", "category": "경비", "base": "labor_subtotal", "rate": "0.02",
         "when": {lift_input: False}, "cite": {"chunk_id": cost_chunk, "quote": quote}},
        {"name": "공구손료 및 경장비(고소작업대 시공)", "category": "경비", "base": "labor_subtotal", "rate": "0.10",
         "when": {lift_input: True}, "cite": {"chunk_id": cost_chunk, "quote": quote}}]
    simple_crew_table(
        package, table=table, output_row=sizes_input, output_column={"column": output_unit_row},
        crew=["배관공", "보통인부"], equipment=[], quantity_input="quantity",
        steps=["관규격 행의 일당 시공량(m)을 고른다.", "시공위치(화장실 -17%, 기계실 -23%, 옥외 +11%) 또는 고소작업대(시저형) +26%를 적용한다.",
               "물량 ÷ 시공량으로 작업일수를 구하고 인원을 곱한다. 공구손료는 인력시공 2%, 고소작업대 시공 10%."],
        source=f"PDF {section} 표 및 비고", reason=GENERIC_REASON + " 비고의 시공위치 요율·26% 가산을 출력 보정으로 표현한다.",
        crew_column={"column_template": "{trade}", "row_input": sizes_input},
        extra={"output_adjustments": adjustments})


@promotion("기계설비/1-2-2")
def welded_piping(package: dict) -> None:
    chunk = chunk_for("1-2-2", "공구손료 및 경장비(절단기, 자체 추진 고소작업대(시저형) 등)의 기계경비는 인력품의 2%(인력시공)", "기계설비")
    indoor_pipe_family(
        package, table="p705-t0", rate_table="p705-t1", sizes_input="pipe_size", lift_input="scissor_lift_used",
        location_input="location", output_unit_row="시공량(m)", cost_chunk=chunk, section="704~705쪽 1-2-2",
        outputs=("132", "115", "100", "85", "70", "57", "50", "37", "32", "25", "19", "15", "12", "11", "8"),
        crew_by_size=[3] * 13 + [4] * 2)


@promotion("기계설비/1-3-4")
def press_piping(package: dict) -> None:
    chunk = chunk_for("1-3-4", "공구손료 및 경장비(절단기, 자체 추진 고소작업대(시저형) 등)의 기계경비는 인력품의 2%(인력시공)", "기계설비")
    indoor_pipe_family(
        package, table="p709-t0", rate_table="p709-t1", sizes_input="pipe_size", lift_input="lift_used",
        location_input="location", output_unit_row="시공량(m)", cost_chunk=chunk, section="708~709쪽 1-3-4",
        outputs=("80", "60", "50", "40", "35", "32", "25", "21", "16", "14"), crew_by_size=[3] * 10)


def rename_input(package: dict, old: str, new: str) -> None:
    """공통 조건 이름(duration·work_category 등)과 겹치는 명세 입력 이름을 바꾼다. 같은 이름이면 상담 계층이
    공종 입력을 공통 조건으로 읽어 허용값이 맞지 않는다고 거절한다. 값·허용값·원문은 그대로 둔다."""
    def walk(value):
        if isinstance(value, dict):
            return {(new if key == old else key): walk(child) for key, child in value.items()}
        if isinstance(value, list):
            return [walk(child) for child in value]
        return new if value == old else value
    package["draft"] = walk(package["draft"])


@promotion("공통/2-2-5")
def scaffold_loss_rate(package: dict) -> None:
    rename_input(package, "duration", "use_duration")


@promotion("공통/2-2-6")
def axle_loss_rate(package: dict) -> None:
    rename_input(package, "duration", "use_duration")


@promotion("기계설비/9-1-2")
def misc_steel_work(package: dict) -> None:
    rename_input(package, "work_category", "steel_work_kind")


def _i(name):
    return {"input": name}


def _n(value):
    return {"number": value}


@promotion("공통/8-2-1")
def bulldozer_capacity(package: dict) -> None:
    """불도저 시간당 작업량 Q = 60·q·f·E / cm. 표 조회·가감을 derived로, 결과는 금액이 아닌 참조 줄로 낸다.

    원문이 정하지 않은 조합(작업현장 이동의 '3단 또는 4단', 타이어형의 굴착·제방·수중, 연한지반 굴착운반의 무한궤도)은 막는다.
    운반거리는 원문 e 표 라벨(10이하, 20…80)에 해당할 때만 e를 정하고 사이값은 정하지 않는다.
    """
    spec = package["draft"]
    works = ["굴착/굴착운반/발근/석재류집적", "흐트러진상태 토사운반", "연한지반 굴착운반",
             "평탄/흐트러진상태 정지/전압", "제방 상향작업", "수중작업", "작업현장 이동"]
    f = field(spec, "work_type")
    f["allowed_values"] = works
    f["source"] = "PDF 169~170쪽 2. 1회 싸이클 시간 [주]"
    # (종류, 작업) -> (전진단, 후진단, 근거 주)
    gears = {("무한궤도", works[0]): (1, 1, "①"), ("무한궤도", works[1]): (2, 2, "②"),
             ("무한궤도", works[3]): (3, 3, "③"), ("무한궤도", works[4]): (1, 2, "④"),
             ("무한궤도", works[5]): (1, 1, "⑤"),
             ("타이어", works[1]): (1, 1, "①"), ("타이어", works[2]): (1, 1, "①"), ("타이어", works[3]): (2, 2, "②")}
    blocked = []
    for kind in ("무한궤도", "타이어"):
        for work in works:
            if (kind, work) in gears:
                continue
            reason = ("원문은 작업현장 이동에 전진 3단 또는 4단(무한궤도) / 2단 또는 3단(타이어)을 쓴다고만 하며 하나로 정하지 않는다."
                      if work == works[6] else "원문 [주]가 이 종류·작업 조합의 변속 단수를 정하지 않는다.")
            blocked.append({"condition": f"{kind} · {work}: 변속 단수가 원문에 없음",
                            "blocked_if_all": [{"input": "bulldozer_type", "op": "==", "value": kind},
                                               {"input": "work_type", "op": "==", "value": work}],
                            "reason": reason, "source": "PDF 170쪽 1회 싸이클 시간 [주]",
                            "cite": {"table_id": "p226-t0" if kind == "무한궤도" else "p226-t1"}})
    tables = {t["id"]: t["values"] for t in spec["tables"]}
    eq = lambda name, value: {"input": name, "op": "==", "value": value}
    # 원문 표의 '-' 칸(해당 없음)에 걸리는 조합은 값으로 대체하지 않고 막는다.
    for kind, row in tables["p225-t0"].items():
        for capacity, cell in row.items():
            if cell.strip() == "-":
                blocked.append({"condition": f"{kind} {capacity}ton: 원문 qﾟ 표에 없는 종류·규격",
                                "blocked_if_all": [eq("bulldozer_type", kind), eq("bulldozer_capacity", capacity)],
                                "reason": "원문 qﾟ 표의 이 칸은 '-'(해당 없음)이다.",
                                "source": "PDF 169쪽 가. qﾟ의 값", "cite": {"table_id": "p225-t0"}})
    for soil, row in tables["p225-t2"].items():
        for column, cell in row.items():
            if cell.strip() == "-":
                state, site = column.rsplit(" ", 1)
                blocked.append({"condition": f"{soil} · {state} · {site}: 원문 E 표에 없는 조합",
                                "blocked_if_all": [eq("soil_type", soil), eq("soil_state", state),
                                                   eq("site_condition", site)],
                                "reason": "원문 E 표의 이 칸은 비어 있다('-').",
                                "source": "PDF 169쪽 다. E의 값", "cite": {"table_id": "p225-t2"}})
    for (kind, work), (forward, backward, _) in gears.items():
        speeds = tables["p226-t0" if kind == "무한궤도" else "p226-t1"]
        for capacity, row in speeds.items():
            if row.get(f"전진 {forward}단", "-").strip() == "-" or row.get(f"후진 {backward}단", "-").strip() == "-":
                blocked.append({"condition": f"{kind} {capacity}ton · {work}: 해당 단의 속도가 원문에 없음",
                                "blocked_if_all": [eq("bulldozer_type", kind), eq("bulldozer_capacity", capacity),
                                                   eq("work_type", work)],
                                "reason": f"원문 V1·V2 표에 전진 {forward}단 또는 후진 {backward}단 속도가 '-'이다.",
                                "source": "PDF 170쪽 V1 및 V2의 값", "cite": {"table_id": "p226-t0" if kind == "무한궤도" else "p226-t1"}})
    blocked.append({"condition": "운반거리 80m 초과: 원문 e 표 범위(10이하~80) 밖",
                    "blocked_if": {"input": "transport_distance", "op": ">", "value": "80"},
                    "reason": "원문 e 값 표는 운반거리 80m까지만 있어 80m를 넘으면 e를 정하지 않는다(외삽하지 않음).",
                    "source": "PDF 169쪽 나. e의 값", "cite": {"table_id": "p225-t1"}})
    spec["blocked"] = blocked
    # p225-t0은 행 라벨(무한궤도·타이어)이 청크 텍스트에 없어(파싱 손실) 칸 인용이 검증되지 않는다. 값은 PDF 이미지로 대조했다.
    for table in spec["tables"]:
        refresh_table_citations(package, table["id"])

    def speed(name: str, offset: int) -> dict:
        cases = []
        for (kind, work), gear in gears.items():
            cases.append({"when": {"bulldozer_type": kind, "work_type": work},
                          "table": "p226-t0" if kind == "무한궤도" else "p226-t1", "row_input": "bulldozer_capacity",
                          "column": ("전진 " if offset == 0 else "후진 ") + f"{gear[offset]}단"})
        return {"name": name, "kind": "table_cell", "cases": cases, "unit": "m/분"}

    bands = [{"label": "10이하", "at_most": "10"}] + [
        {"label": str(d), "equals": str(d)} for d in range(20, 90, 10)]
    derived = [
        {"name": "q_base", "kind": "table_cell", "unit": "㎥", "source": "PDF 169쪽 가. qﾟ의 값",
         "cases": [{"table": "p225-t0", "row_input": "bulldozer_type", "column_input": "bulldozer_capacity"}]},
        {"name": "e", "kind": "table_cell", "unit": "", "source": "PDF 169쪽 나. e의 값", "band_input": "transport_distance",
         "bands": bands, "cases": [{"table": "p225-t1", "row": "e"}]},
        {"name": "E_table", "kind": "table_cell", "unit": "", "source": "PDF 169쪽 다. E의 값",
         "cases": [{"table": "p225-t2", "row_input": "soil_type", "column_join": ["soil_state", "site_condition"]}]},
        {"name": "E_deduction", "kind": "sum_terms", "source": "PDF 169쪽 [주] ④ 정지작업 겸용 0.1, ⑤ 터파기 0.05",
         "terms": [{"when": {"is_grading": True}, "value": "1/10"}, {"when": {"is_trenching": True}, "value": "1/20"}]},
        {"name": "E", "kind": "expression", "source": "PDF 169쪽 [주] ④⑤ E에서 해당 값을 뺀다",
         "expression": {"sub": [_i("E_table"), _i("E_deduction")]}},
        speed("V1", 0), speed("V2", 1),
        {"name": "q", "kind": "expression", "source": "PDF 168쪽 q = qﾟ × e", "unit": "㎥",
         "expression": {"mul": [_i("q_base"), _i("e")]}},
        {"name": "cm", "kind": "expression", "source": "PDF 169쪽 cm = L/V1 + L/V2 + t(0.25분)", "unit": "분",
         "expression": {"add": [{"div": [_i("transport_distance"), _i("V1")]},
                                {"div": [_i("transport_distance"), _i("V2")]}, _n("1/4")]}},
    ]
    outputs = [
        {"kind": "formula", "name": "1회 싸이클 시간 cm", "resource_kind": "reference", "unit": "분",
         "expression": _i("cm"), "formula": "cm = L/V1 + L/V2 + 0.25", "source": "PDF 169쪽 2. 1회 싸이클 시간"},
        {"kind": "formula", "name": "시간당 작업량 Q", "resource_kind": "reference", "unit": "㎥/hr",
         "expression": {"div": [{"mul": [_n("60"), _i("q"), _i("f_coefficient"), _i("E")]}, _i("cm")]},
         "formula": "Q = 60 × q × f × E / cm", "source": "PDF 168쪽 8-2-1 산정식"},
    ]
    finish(package, "formula",
           "표 조회값(qﾟ·e·E·V1·V2)과 가감을 파생 입력으로 만든 뒤 선언형 식으로 시간당 작업량을 계산한다. 금액이 아닌 참조 값이다.",
           ["qﾟ·e·E 표에서 값을 고르고 정지·터파기면 E에서 0.1·0.05를 뺀다.", "작업 종류별 변속 단수로 V1·V2를 고른다.",
            "cm = L/V1 + L/V2 + 0.25, q = qﾟ×e, Q = 60×q×f×E/cm를 계산한다."],
           {"derived": derived, "outputs": outputs}, model="formula",
           source="PDF 168~170쪽 8-2-1 산정식")


def main() -> int:
    only = set(sys.argv[1:])
    chunks = chunks_by_id_from_list([json.loads(l) for l in CHUNKS.read_text(encoding="utf-8").splitlines() if l.strip()])
    status = 0
    for key, function in PROMOTIONS.items():
        if only and key not in only:
            continue
        path = SPECS / f"{key.split('/')[0]}/{key.split('/')[1]}.json"
        package = json.loads(path.read_text(encoding="utf-8"))
        function(package)
        global _CHUNK_INDEX
        if _CHUNK_INDEX is None:
            _CHUNK_INDEX = chunks
        repair_line_crossing_quotes(package, chunks)
        path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        result = validate_one(path, ROOT / "data/drafts", chunks, None)
        print(key, "ok" if result["ok"] else result["format_issues"] + result["citation_issues"])
        status |= 0 if result["ok"] else 1
    return status


if __name__ == "__main__":
    sys.exit(main())
