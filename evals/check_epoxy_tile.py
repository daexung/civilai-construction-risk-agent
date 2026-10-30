"""Source-value check for epoxy tile setting, section 3-2-4."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew


def main() -> int:
    path = next(p for p in (ROOT / "data/drafts/specs").rglob("3-2-4.json")
                if "p643-t1" in p.read_text(encoding="utf-8"))
    spec = json.loads(path.read_text(encoding="utf-8"))["draft"]
    tile_size = next(f for f in spec["inputs"] if f["name"] == "tile_size")
    result = adjusted_daily_crew(spec, {"tile_size": tile_size["allowed_values"][1],
                                        "quantity": "100", "special_shape": False})
    assert result["status"] == "computed", result
    assert result["daily_volume_m3"] == "30", result
    assert result["person_days"] == {"타일공": "10", "보통인부": "10/3"}, result
    blocked = adjusted_daily_crew(spec, {"tile_size": tile_size["allowed_values"][1],
                                         "quantity": "100", "special_shape": True})
    assert blocked["status"] == "blocked", blocked
    print("PASS PDF p.587: 30㎡/day, 3 tile setters and 1 helper for 100㎡.")
    print("PASS shaped tiles are blocked under source note ③.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
