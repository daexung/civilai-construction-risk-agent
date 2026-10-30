from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
from fractions import Fraction
import pymupdf,re
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
from backend.agent.nodes.compute import compute
from pipeline.validate_drafts import validate_one,chunks_by_id_from_list
p=ROOT/"data/drafts/specs/유지관리/2-1-8.json";pkg=json.loads(p.read_text(encoding="utf8"));spec=pkg["draft"]
PDF=ROOT/"data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
with pymupdf.open(PDF) as pdf:
 text=re.sub(r"\s+","",pdf[932].get_text())
import re
for token in ("2-1-8소파보수(표층)","포장공인34003140350","보통인부인111","로더(타이어)+소형노면파쇄기0.95㎥대111","트럭2.5ton대222","30㎡이하60㎡이하120㎡이하180㎡이하180㎡초과시공량할증계수0.790.891.001.121.26","현장별시공여건에대한시공량의할증은다음표를참고하여적용한다"):
 assert token in text,token
source={"A-Type":("p933-t3",[30,60,120,180,181],["0.79","0.89","1.00","1.12","1.26"],400),"B-Type":("p933-t4",[15,30,60,90,91],["0.79","0.89","1.00","1.12","1.26"],140),"C-Type":("p934-t0",[5,10,20,30,31],["0.79","0.89","1.00","1.12","1.26"],50)}
checks=0
for typ,(tid,areas,coefficients,base) in source.items():
 for area,coefficient in zip(areas,coefficients):
  inputs={"site_type":typ,"area":"100","avg_area_per_spot":str(area),"overlay_only":False}
  r=adjusted_daily_crew(spec,inputs,labor_only=True);assert r["status"]=="computed",(inputs,r)
  assert Fraction(r["daily_volume_m3"])==Fraction(base)*Fraction(coefficient),(inputs,r.get("daily_volume_m3"),coefficient)
  days=Fraction(100,1)/(Fraction(base)*Fraction(coefficient))
  assert Fraction(r["work_days"])==days,(inputs,r["work_days"],days)
  assert Fraction(r["person_days"]["포장공"])==days*3 and Fraction(r["person_days"]["보통인부"])==days
  assert set(r["equipment_days"])=={"로더(타이어)+소형노면파쇄기","로더(타이어)","진동롤러(진동+타이어)","아스팔트스프레이어","트럭"}
  expected_counts={"로더(타이어)+소형노면파쇄기":1,"로더(타이어)":1,"진동롤러(진동+타이어)":1,"아스팔트스프레이어":1,"트럭":2}
  for name,count in expected_counts.items():assert Fraction(r["equipment_days"][name])==days*count,(inputs,name,r["equipment_days"][name])
  cited=r["provenance"]["daily_volume_m3"]["coefficients"][0];assert (cited["table"],cited["column"],cited["value"])==(tid,next(k for k,v in spec["tables"][2 if typ=='A-Type' else 3 if typ=='B-Type' else 4]["values"]["시공량 할증계수"].items() if v==coefficient and ((area<=int(re.search(r"[\d]+",k).group()) and "초과" not in k) or ("초과" in k and area>int(re.search(r"[\d]+",k).group())))),coefficient)
  checks+=1
blocked=adjusted_daily_crew(spec,{"site_type":"A-Type","area":"100","avg_area_per_spot":"30","overlay_only":True},labor_only=True);assert blocked["status"]=="blocked" and blocked.get("citations"),blocked
active=compute({"spec_id":spec["id"],"inputs":{"site_type":"C-Type","area":"100","avg_area_per_spot":"31","overlay_only":False}});assert active["status"]=="COMPUTED",active
chunks_path=ROOT/"data/processed/chunks.all.jsonl";chunks=[json.loads(x) for x in chunks_path.read_text(encoding="utf8").splitlines() if x]
validation=validate_one(p,ROOT/"data/drafts/specs",chunks_by_id_from_list(chunks),hashlib.sha256(chunks_path.read_bytes()).hexdigest());assert validation["ok"],validation
record={"section":"2-1-8","result":"PASS","scope":{"exact_daily_routes":checks,"original_workcrew_and_equipment_rows":7,"coefficient_boundaries_and_over_boundaries":15,"type_specific_base_outputs_and_crew":True,"five_equipment_rows_each_type":True,"overlay_policy_blocked":True,"active_compute_node":"passed","draft_validation":"passed"},"source_evidence":{"pdf":"data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf","physical_pages":[933,934],"printed_pages":[877,878],"image":"evals/runtime_validation/followup-p933.png","page_text_and_layout":"verified visually; original output cells are merged across labor rows, carried explicitly only to those two crew rows"},"unresolved":"overlay-only rule excludes one paving worker and one small breaker, but the source equipment row is a combined loader+breaker label. That route remains blocked instead of guessing a split.","not_verified":["pricing","consultation","multi-item aggregation","Excel"],"validation":validation,"hashes":{"spec_sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"chunks_all_sha256":hashlib.sha256(chunks_path.read_bytes()).hexdigest()}}
out=ROOT/"evals/runtime_validation/maintenance-2-1-8-surface-source-audit-2026-10-19.json";out.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf8");print(json.dumps(record,ensure_ascii=False,indent=2))
