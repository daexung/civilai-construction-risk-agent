"""Source-value check for ALC panel installation."""
import json
from pathlib import Path
import sys
from fractions import Fraction

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew


def main() -> int:
    path = next(p for p in (ROOT / "data/drafts/specs").rglob("2-3-2.json")
                if "p640-t0" in p.read_text(encoding="utf-8"))
    spec = json.loads(path.read_text(encoding="utf-8"))["draft"]
    expected = {"75": "22", "100": "19", "125": "16", "150": "14", "175": "13", "200": "11"}
    for thickness, daily_rate in expected.items():
        result = adjusted_daily_crew(spec, {"panel_thickness": thickness, "area": "100"})
        assert result["status"] == "computed", (thickness, result)
        assert result["daily_volume_m3"] == daily_rate, (thickness, result)
        assert Fraction(result["person_days"]["조적공"]) == Fraction(300, int(daily_rate)), result
        assert Fraction(result["person_days"]["보통인부"]) == Fraction(100, int(daily_rate)), result
    print("PASS PDF p.584: all six panel thickness production rates and 3+1 crew table rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
