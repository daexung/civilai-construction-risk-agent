"""Verify exact exterior waterproofing floor-band rates on original p.607."""
import hashlib
import itertools
import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from pipeline.validate_drafts import DEFAULT_CHUNKS, DEFAULT_DRAFTS_DIR, file_sha256, load_chunks, validate_one

SPEC = ROOT / "data/drafts/specs/건축/6-5-2.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
IMAGE = ROOT / "evals/runtime_validation/source-p663-waterproofing.png"
AUDIT = ROOT / "evals/runtime_validation/per-unit-6-5-2-source-floor-bands-audit-2026-10-19.json"
BASE = {"방수공": {"바름 1층(회)": "0.014", "바름 2층(회)": "0.021", "뿜칠 1층(회)": "0.011", "뿜칠 2층(회)": "0.017"},
        "보통인부": {"바름 1층(회)": "0.003", "바름 2층(회)": "0.005", "뿜칠 1층(회)": "0.003", "뿜칠 2층(회)": "0.004"}}
BANDS = [(1,3,"0"),(4,6,"5%"),(7,9,"8%"),(10,12,"12%"),(13,15,"16%"),(16,18,"20%")]

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    package=json.loads(SPEC.read_text(encoding="utf-8")); spec=package["draft"]
    raw=next(t for t in spec["tables"] if t["id"]=="p663-t2")["values"]
    assert raw==BASE, raw
    bandtable=next(t for t in spec["tables"] if t["id"]=="p663-t3")["values"]["인력품"]
    assert [bandtable[c] for c in ("1,2,3층","4,5,6층","7,8,9층","10,11,12층","13,14,15층","16,17,18층")] == [x[2] for x in BANDS]
    routes=[]
    for floor,method in itertools.product(range(1,19),BASE["방수공"]):
        percent=next(Fraction(x[2].replace('%',''))/100 for x in BANDS if x[0]<=floor<=x[1])
        result=per_unit(spec,{"method_and_layers":method,"quantity":"100","floor_level":floor,"crane_used":False})
        assert result["status"]=="computed", (floor,method,result)
        expected={trade:Fraction(rate)*(1+percent) for trade,cols in BASE.items() for col,rate in cols.items() if col==method}
        actual={line["name"]:Fraction(line["exact"]) for line in result["unit_lines"]}
        assert actual==expected,(floor,method,actual,expected)
        selected=[c for line in result["unit_lines"] for c in line["citations"] if c.get("internal_id")=="p663-t3"]
        expected_column=next(c for a,b,c in [(1,3,"1,2,3층"),(4,6,"4,5,6층"),(7,9,"7,8,9층"),(10,12,"10,11,12층"),(13,15,"13,14,15층"),(16,18,"16,17,18층")] if a<=floor<=b)
        assert selected and all(c.get("column")==expected_column for c in selected)
        routes.append({"floor":floor,"method":method,"percentage":str(percent*100),"rates":{k:str(v) for k,v in actual.items()}})
    blocked=per_unit(spec,{"method_and_layers":"바름 1층(회)","quantity":"1","floor_level":19,"crane_used":False})
    assert blocked["status"]=="blocked" and any(c.get("internal_id")=="p663-x14" for c in blocked.get("citations",[]))
    validation=validate_one(SPEC,DEFAULT_DRAFTS_DIR.resolve(),load_chunks(DEFAULT_CHUNKS),file_sha256(DEFAULT_CHUNKS)); assert validation["ok"],validation
    audit={"id":spec["id"],"status":"source_cells_and_1_to_18_floor_routes_verified","source":{"physical_page":663,"printed_page":607,"image":"evals/runtime_validation/source-p663-waterproofing.png","image_sha256":sha(IMAGE),"pdf_sha256":sha(PDF),"base_cells":16,"floor_rate_cells":6,"visual_review":True},"runtime":{"exact_floor_method_routes":len(routes),"routes":routes,"floor_19_plus":"blocked; original says +4% per each 3-floor increase, but start point/interval calculation was left unresolved","validator":validation,"full_rule_verification":False},"remaining_source_items":["materials separate; brushing use adds 10% material quantity, material cost unavailable","crane rental separately billed; not priced"],"spec_sha256":sha(SPEC),"per_unit_sha256":sha(ROOT/"backend/agent/tools/calc/per_unit.py")}
    AUDIT.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"base_cells":16,"floor_cells":6,"routes":len(routes),"floor_19":blocked["status"],"validator":validation["ok"]},ensure_ascii=False))

if __name__=="__main__": main()
