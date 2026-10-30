"""Source-cell and exact mixed-denominator audit for mechanical 12-2-1."""
from __future__ import annotations
import hashlib, json, os, sys
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.estimate import tools as estimate_tools
from backend.agent.nodes import select as select_node
from backend.agent.tools.source import citation as citation_runtime
from pipeline.validate_drafts import chunks_by_id_from_list, check_table_citation, validate_one

SPEC_PATH = ROOT / "data/drafts/specs/기계설비/12-2-1.json"
PDF_PATH = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
AUDIT_PATH = ROOT / "evals/runtime_validation/per-unit-12-2-1-device-item-units-2026-10-19.json"

# Independently transcribed from the p.719 table, with ditto units resolved from the preceding row.
EXPECTED = [
 ("실내온도조절기","규격 전기전자식","개","0.22","개"),
 ("실내온도조절기","규격 공기식","개","0.29","〃"),
 ("삽입식온도조절기","규격 덕트용","개","0.43","개"),
 ("삽입식온도조절기","규격 배관용","개","0.90","〃"),
 ("습도조절기","규격 전기전자식","개","0.22","개"),
 ("습도조절기","규격 공기용","개","0.29","〃"),
 ("습도조절기","규격 덕트용","개","0.41","〃"),
 ("댐퍼용모터","계장공","조","0.48","조"),
 ("자동조절밸브용모터","계장공","조","0.22","〃"),
 ("압력조정기","계장공","조","0.10","〃"),
 ("스탭컨트롤러","계장공","조","0.48","〃"),
 ("수동조작기","계장공","개","0.38","개"),
 ("온습도지시계","계장공","개","1.90","〃"),
 ("기록계","계장공","개","1.90","〃"),
 ("액면지시계류","계장공","개","1.90","〃"),
 ("전자식패널","계장공","개","0.95","〃"),
 ("릴레이류","계장공","개","0.38","〃"),
 ("현장반","규격 벽붙이형","면","2.85","면"),
 ("현장반","규격 스탠드형","면","6.65","〃"),
 ("공업용압력발신기","계장공","개","1.90","개"),
 ("공업용차압발신기","계장공","개","1.90","〃"),
]

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def estimate_flow(spec, item, selected_spec, unit, rate):
    hit={"rank":1,"section_no":"12-2-1","division":"기계설비","section":spec["title"],"page":719,"table_id":"p775-t0","text":spec["title"],"chunk_id":"p775-t0"}
    spec_map={("기계설비","12-2-1"):[spec]}
    with patch.object(citation_runtime,"_pages",return_value=defaultdict(lambda:{"printed_page":719,"division":"기계설비"})), patch.object(estimate_tools,"specs_by_section",return_value=spec_map), patch.object(estimate_tools,"load_specs",return_value={spec["id"]:spec}), patch.object(select_node,"specs_by_section",return_value=spec_map):
        session=estimate_tools.new_estimate("자동제어기기 설치")
        estimate_tools.find_work(session,hits=[hit])
        result=estimate_tools.compute_labor(session)
        for field,value in (("device_type",item),("spec",selected_spec)):
            estimate_tools.set_conditions(session,value,values={field:{"value":value,"evidence":value}},source="answer")
            result=estimate_tools.compute_labor(session)
        question=next(q for q in result.get("missing",[]) if q["field"]=="quantity")
        assert question.get("unit")==unit,question
        estimate_tools.set_conditions(session,f"2{unit}",quantity={"value":"2","unit":unit,"evidence":f"2{unit}"},source="text")
        result=estimate_tools.compute_labor(session)
        assert result.get("status")=="ok",result
        lines=result["data"]["unit_lines"]
        assert len(lines)==1 and Fraction(lines[0]["exact"])==Fraction(rate),lines
        assert result["data"]["unit_basis"]["per"]==f"1{unit}"
        return {"unit":unit,"rate":lines[0]["exact"],"status":"ok"}

def main():
    os.environ.update(AGENT_MODE="tools",AGENT_LLM="off",AGENT_OFFLINE="1")
    package=json.loads(SPEC_PATH.read_text(encoding="utf-8")); spec=package["draft"]
    chunks=[json.loads(x) for x in (ROOT/"data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    index=chunks_by_id_from_list(chunks); source=index["p775-t0"]["text"]
    pdf_text=pymupdf.open(PDF_PATH)[774].get_text("text")
    assert "12-2-1 자동제어기기 설치" in source and "소운반이 포함" in pdf_text
    assert len(EXPECTED)==21
    routes=[]
    for item,col,unit,rate,marker in EXPECTED:
        row=item if col=="계장공" else f"{item} | {col}"
        source_row=f"{row} | 단위 {marker} | 계장공 {rate}"
        assert source_row in source,(source_row,source)
        table=next(t for t in spec["tables"] if t["id"]=="p775-t0")
        value=table["values"][item][col]
        assert value==rate,(item,col,value,rate)
        output=per_unit(spec,{"device_type":item,"spec":col,"quantity":"1"})
        assert output["status"]=="computed",(item,col,output)
        line=output["unit_lines"][0]
        assert line["unit"]==f"인/{unit}" and Fraction(line["exact"])==Fraction(rate),line
        assert line["citations"][0].get("row")==row,(row,line["citations"])
        # The source table prints ditto marks for inherited units; check that literal cell,
        # while the normalized denominator is checked independently in the runtime result.
        for c,v in (("단위",marker),("계장공",rate)):
            cite={"table_id":"p775-t0","row":row,"column":c,"value":v}
            assert check_table_citation(index,cite) is None,cite
        routes.append({"device":item,"spec":col,"unit":unit,"rate":rate,"source_row":row})
    representatives={"개":("실내온도조절기","규격 전기전자식","0.22"),"조":("댐퍼용모터","계장공","0.48"),"면":("현장반","규격 벽붙이형","2.85")}
    flows={u:estimate_flow(spec,args[0],args[1],u,args[2]) for u,args in representatives.items()}
    validation=validate_one(SPEC_PATH,ROOT/"data/drafts/specs",index,None)
    assert not validation.get("issues"),validation
    audit={"id":spec["id"],"status":"all_mixed_device_units_and_source_rates_verified","source":{"physical_page":775,"printed_page":719,"visual":"original p.719 table image manually checked against 21 row entries; exact unit markers and adjacent ditto inheritance independently transcribed","source_rows_checked":21,"unit_and_labor_cells_checked":42,"routes":routes,"pdf_sha256":sha(PDF_PATH)},"runtime":{"computed_routes":len(routes),"estimate_flows_by_unit":flows,"validation_issues":validation.get("issues",[])},"rule_scope":{"all_rules_fully_verified":False,"source_note":"Small transport is included per source note; separately quantified note adjustments were not tested."},"spec_sha256":sha(SPEC_PATH),"chunks_sha256":sha(ROOT/"data/processed/chunks.all.jsonl"),"runtime_per_unit_sha256":sha(ROOT/"backend/agent/tools/calc/per_unit.py"),"runtime_fill_sha256":sha(ROOT/"backend/agent/nodes/fill.py")}
    AUDIT_PATH.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":audit["status"],"rows":21,"cells":42,"flows":flows,"fully_verified_rules":False},ensure_ascii=False))

if __name__=="__main__": main()
