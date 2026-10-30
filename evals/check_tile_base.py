"""Source-value check for the tile base-preparation daily crew."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew


def main() -> int:
    path = next(p for p in (ROOT / "data/drafts/specs").rglob("3-1-1.json")
                if "p641-t0" in p.read_text(encoding="utf-8"))
    spec = json.loads(path.read_text(encoding="utf-8"))["draft"]
    surface = next(f for f in spec["inputs"] if f["name"] == "surface_type")
    inputs = {"surface_type": surface["allowed_values"][0], "area": "100", "thickness": "24"}
    result = adjusted_daily_crew(spec, inputs)
    assert result["status"] == "computed", result
    assert result["daily_volume_m3"] == "45", result
    assert result["person_days"] == {"미장공": "40/9", "보통인부": "20/9"}, result
    beyond = adjusted_daily_crew(spec, {**inputs, "thickness": "24.1"})
    assert beyond["status"] == "blocked", beyond
    print("PASS PDF p.585: wall output 45㎡/day; 2 plasterers + 1 helper for 100㎡.")
    print("PASS thickness >24mm blocked by source scope.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
