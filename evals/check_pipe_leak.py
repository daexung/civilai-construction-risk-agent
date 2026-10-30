"""Source-value check for maintenance section 4-3-3."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew


def main() -> int:
    from pypdf import PdfReader
    pdf = next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))
    source = PdfReader(pdf).pages[981].extract_text() or ""
    assert "배관공인22.8" in "".join(source.split()), source[-1200:]
    path = next(p for p in (ROOT / "data/drafts/specs").rglob("4-3-3.json")
                if "p982-t1" in p.read_text(encoding="utf-8"))
    spec = json.loads(path.read_text(encoding="utf-8"))["draft"]
    result = adjusted_daily_crew(spec, {"inspection_count": "7", "pipe_size": "50"})
    assert result["status"] == "computed", result
    assert result["work_days"] == "2.5", result
    assert result["person_days"] == {"배관공": "5"}, result
    assert result["unit_lines"][0]["exact"] == "5/7", result
    blocked = adjusted_daily_crew(spec, {"inspection_count": "7", "pipe_size": "50.1"})
    assert blocked["status"] == "blocked", blocked
    print("PASS PDF p.926 source: 2 fitters / 2.8 tests per day; 7 tests = 5 person-days.")
    print("PASS pipe size >50mm is blocked by source scope.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
