"""Use the source's 1,000-piece basis and route Stud-bolt cost by welding method."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/건축/1-4-2.json"
METHODS = ["데크플레이트 자동용접", "데크플레이트 수동용접",
           "지하 철골 기둥 자동용접", "지하 철골 기둥 수동용접"]


def main() -> None:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    note = spec["quantity_model"]["params"]["note_adjustments"][0]
    note["implemented_by"] = "unit_rate_table source denominator 인/1,000개"
    spec["cost_rules"] = [
        {"name": f"공구손료 및 경장비 ({'자동용접' if '자동용접' in method else '수동용접'})",
         "category": "경비", "base": "labor_subtotal",
         "rate": "0.22" if "자동용접" in method else "0.18",
         "when": {"installation_type": method},
         "cite": {"chunk_id": "p632-x9",
                  "quote": "공구손료 및 경장비(용접기 등)는 자동용접인 경우 인력품의 22%, 수동용접인 경우 인력품의 18%로 계상한다."}}
        for method in METHODS
    ]
    package["open_questions"] = [
        "데크플레이트에서 1열 등 2열과 다른 시공의 품 조정은 원문에 명시되지 않아 별도 정책 검토가 필요합니다.",
        "지하 철골 기둥에서 탑다운공법 이외 설치에 대한 적용 여부는 원문 기준에 없어 검토 대상으로 유지합니다.",
        "잡재료는 주재료비의 5%이나 주재료 단가가 제공되지 않아 별도 계산되지 않습니다.",
    ]
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("connected explicit source denominator and conditional costs")


if __name__ == "__main__":
    main()
