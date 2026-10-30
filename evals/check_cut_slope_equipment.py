"""Source-value check for soil-class equipment output in 3-5-1."""
import json
from fractions import Fraction
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew


def main() -> int:
    path = next(p for p in (ROOT / "data/drafts/specs").rglob("3-5-1.json")
                if "p133-t1" in p.read_text(encoding="utf-8"))
    spec = json.loads(path.read_text(encoding="utf-8"))["draft"]
    source_rates = {"모래･사질토･점토･점질토": 390, "연질토･불순자갈": 250,
                    "호박돌 섞인 고결토･경질토": 230, "풍화암": 120,
                    "연암": 80, "보통암･경암": 60}
    for soil, daily_rate in source_rates.items():
        result = adjusted_daily_crew(spec, {"soil_type": soil, "quantity": "1000"})
        assert result["status"] == "computed", (soil, result)
        assert Fraction(result["work_days"]) == Fraction(1000, daily_rate), (soil, result)
        assert len(result["unit_lines"]) == 1, (soil, result)
        equipment = result["unit_lines"][0]
        assert equipment["kind"] == "equipment", equipment
        assert Fraction(equipment["exact"]) == Fraction(8, daily_rate), equipment
        expected_name = "대형브레이커" if soil == "보통암･경암" else "굴착기"
        assert equipment["name"] == expected_name, equipment
        assert equipment["citations"], equipment
    print("PASS PDF p.77: all six soil classes select source equipment and output; equipment-days and hours reconcile.")
    print("Ripper cost remains explicitly out of scope at 2% of excavator machine cost.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
