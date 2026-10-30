"""Expose the source's 0.04 kg/m3 soap coefficient through per_unit materials."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/기계설비/13-7-22.json"


def main() -> None:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    note = next(item for item in spec["quantity_model"]["params"]["note_adjustments"]
                if "가루비누" in item.get("change", ""))
    note["implemented_by"] = "unit_rate_table.additional_materials note-based source_rate"
    spec["quantity_model"]["params"]["additional_materials"] = [{
        "name": "가루비누", "source_rate": "0.04", "basis": "kg/㎥",
        "quantity_input": "volume", "quantity_unit": "㎥", "unit": "kg",
        "source": "PDF 834쪽 [주] ④",
        "cite": {"chunk_id": "p890-x4", "quote": "④ 누설 Check용 가루비누는 ㎥당 0.04㎏ 계상한다."},
    }]
    package["open_questions"] = [
        "가루비누의 사용량은 산출하나, 현장 재료단가가 없어 재료비 금액은 미산정합니다.",
        "원문 추출에 다음 절의 내용이 섞인 사항은 이미 관련되지 않은 범위로 제외되어 있습니다.",
    ]
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("connected 13-7-22 cited material rate to per_unit")


if __name__ == "__main__":
    main()
