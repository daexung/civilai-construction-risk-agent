from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
from fractions import Fraction
import pymupdf,re
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
from backend.agent.nodes.compute import compute
from pipeline.validate_drafts import validate_one,chunks_by_id_from_list
p=ROOT/"data/drafts/specs/공통/3-7-1.json";pkg=json.loads(p.read_text(encoding="utf8"));spec=pkg["draft"]
PDF=ROOT/"data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
with pymupdf.open(PDF) as pdf: text=re.sub(r"\s+","",pdf[133].get_text())
for token in ("3-7-1프리캐스트콘크리트블록설치","인력특별인부인2272422","보통인부인3기계특별인부인2413835보통인부인2크레인대1","0.4인/10본당"):
 assert token in text,token
slopes=["1:1.5 이상","1:1.0이상∼1:1.5 미만","1:1.0 미만"]
data={"인력":([27,24,22],2,3),"기계":([41,38,35],2,2)}; checks=0
for method,(outputs,special,general) in data.items():
 for slope,output in zip(slopes,outputs):
  for yuhang in (0,10,25):
   inp={"method":method,"slope":slope,"quantity":"100","yuhang_quantity":yuhang,"vertical_height_over_20m":False,"fill_required":False,"block_weight":"60" if method=="기계" else "40","avg_slope_length":"20" if method=="기계" else "15"}
   r=adjusted_daily_crew(spec,inp,labor_only=True);assert r["status"]=="computed",(inp,r)
   days=Fraction(100,output);assert Fraction(r["daily_volume_m3"])==output and Fraction(r["work_days"])==days
   assert Fraction(r["person_days"]["특별인부"])==days*special
   assert Fraction(r["person_days"]["보통인부"])==days*general+Fraction(4*yuhang,100)
   assert ("크레인" in r["equipment_days"])==(method=="기계")
   if method=="기계": assert Fraction(r["equipment_days"]["크레인"])==days
   assert r["provenance"]["daily_volume_m3"]["base_output"]["row"]==f"{method} | 일일시공량"
   assert r["provenance"]["daily_volume_m3"]["base_output"]["column"]==f"시공량(㎡) 비탈경사 {slope}"
   checks+=1
for bad in ({"method":"인력","block_weight":"50","avg_slope_length":"10"},{"method":"인력","block_weight":"40","avg_slope_length":"15.1"},{"method":"기계","block_weight":"40","avg_slope_length":"15"}):
 inp={**bad,"slope":slopes[0],"quantity":"1","yuhang_quantity":0,"vertical_height_over_20m":False,"fill_required":False};r=adjusted_daily_crew(spec,inp,labor_only=True);assert r["status"]=="blocked",(inp,r)
for name,value in (("vertical_height_over_20m",True),("fill_required",True)):
 inp={"method":"인력","block_weight":"40","avg_slope_length":"10","slope":slopes[0],"quantity":"1","yuhang_quantity":0,"fill_required":False,"vertical_height_over_20m":False,name:value};r=adjusted_daily_crew(spec,inp,labor_only=True);assert r["status"]=="blocked" if name=="vertical_height_over_20m" else r["status"]=="computed",(name,r)
active=compute({"spec_id":spec["id"],"inputs":{"method":"기계","block_weight":"50","avg_slope_length":"15","slope":slopes[2],"quantity":"100","yuhang_quantity":25,"vertical_height_over_20m":False,"fill_required":True}});assert active["status"]=="COMPUTED",active
chunks_path=ROOT/"data/processed/chunks.all.jsonl";chunks=[json.loads(x) for x in chunks_path.read_text(encoding="utf8").splitlines() if x]
validation=validate_one(p,ROOT/"data/drafts/specs",chunks_by_id_from_list(chunks),hashlib.sha256(chunks_path.read_bytes()).hexdigest());assert validation["ok"],validation
record={"section":"3-7-1","result":"PASS","scope":{"exact_workflow_calculations":checks,"source_numeric_table_cells":12,"yuhang_quantity_cases":[0,10,25],"method_and_slope_output_routes":True,"method_eligibility_rejections":3,"vertical_over_20m_blocked":True,"fill_required_base_scope_computed":True,"active_compute_node":"passed","draft_validation":"passed"},"source_evidence":{"pdf":"data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf","physical_page":134,"printed_page":78,"render":"evals/runtime_validation/followup-p134.png","visual_cells_checked":"method/trade workcrew counts, all six method/slope outputs, machine crane count, and 0.4 per 10 stakes note"},"not_calculated":["backfill/fill when required (source says separately accounted)","pricing","consultation","multi-item aggregation","Excel"],"validation":validation,"hashes":{"spec_sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"chunks_all_sha256":hashlib.sha256(chunks_path.read_bytes()).hexdigest()}}
out=ROOT/"evals/runtime_validation/common-3-7-1-precast-block-source-audit-2026-10-20.json";out.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf8");print(json.dumps(record,ensure_ascii=False,indent=2))
