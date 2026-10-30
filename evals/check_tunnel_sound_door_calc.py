"""Source-based installation/dismantling rates for tunnel sound doors."""
from __future__ import annotations
import glob
import json
import re
from fractions import Fraction
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.per_unit import per_unit

ROOT = Path(__file__).resolve().parents[1]
text = re.sub(r"\s+", "", PdfReader(next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))).pages[114].extract_text() or "")
assert all(x in text for x in ("2.81", "2.53", "1.13", "1.02", "8.0", "5.6", "3차로이하"))
p = next(p for p in glob.glob(str(ROOT / "data/drafts/specs" / "*" / "2-10-3.json"))
         if any(t.get("id") == "p115-t4" for t in json.loads(Path(p).read_text(encoding="utf-8"))["draft"].get("tables", [])))
d = json.loads(Path(p).read_text(encoding="utf-8"))["draft"]
f = {x["name"]: x for x in d["inputs"]}
install, dismantle = f["work_type"]["allowed_values"]
base = {"quantity": "10", "lane_count": f["lane_count"]["allowed_values"][0]}
installed = per_unit(d, {**base, "work_type": install})
assert installed["status"] == "computed", installed
install_rates = {x["name"]: Fraction(x["exact"]) * 10 for x in installed["unit_lines"]}
assert install_rates == {"철공": Fraction(281, 10), "용접공": Fraction(113, 10),
                        "보통인부": Fraction(113, 10), "크레인 50ton": 80, "크레인 10ton": 80}
removed = per_unit(d, {**base, "work_type": dismantle})
assert removed["status"] == "computed", removed
remove_rates = {x["name"]: Fraction(x["exact"]) * 10 for x in removed["unit_lines"]}
assert remove_rates == {"철공": Fraction(253, 10), "보통인부": Fraction(51, 5),
                        "크레인 50ton": 56, "크레인 10ton": 56}
assert "용접공" not in remove_rates
assert removed["provenance"]["excluded_resources"][0]["trade"] == "용접공"
assert per_unit(d, {**base, "work_type": install, "lane_count": f["lane_count"]["allowed_values"][-1]})["status"] == "blocked"
print("PASS source p.59: installation and dismantling labor/crane-hour totals for 10 locations match source rates.")
print("PASS source '-' for dismantling welder is recorded as an excluded resource, not coerced to zero; >3 lanes blocked.")
