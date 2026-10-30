"""Reconstruct three cooling-tower tables from the original PDF's measured grid."""
import json,sys
from pathlib import Path
import fitz
ROOT=Path(__file__).resolve().parents[1]
PDF=ROOT/"data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
CHUNKS=ROOT/"data/processed/chunks.all.jsonl"
SPEC=ROOT/"data/drafts/specs/기계설비/8-1-3.json"
FLOORS={"2층건물":746,"5층건물":747,"9층건물":748}
CAPACITIES=["5","10","20","30","50","80","100","150","200","300","400","500","600"]
LOCATIONS=["1회 옥상","1회 탑옥1층","1회 탑옥3층","2회 탑옥1층","2회 탑옥3층"]
TRADES=["비계공","특별인부"]
def main():
 pdf=fitz.open(PDF); tables={}; transcribed={}; cell_count=0
 for floor,page_no in FLOORS.items():
  found=pdf[page_no-1].find_tables().tables; assert len(found)==1,(page_no,len(found))
  rows=found[0].extract(); assert len(rows)==28 and len(rows[0])==7,(page_no,len(rows),len(rows[0]))
  values={};
  for i,capacity in enumerate(CAPACITIES):
   primary=rows[2+i*2]; secondary=rows[3+i*2]
   assert primary[0]==capacity and primary[1]=="비계공\n특별인부",(page_no,capacity,primary[:2])
   assert secondary[0] is None and secondary[1] is None,(page_no,capacity,secondary[:2])
   values[f"구분 {capacity}"]={}
   for trade,source_row in zip(TRADES,(primary,secondary)):
    for loc,value in zip(LOCATIONS,source_row[2:7]):
     assert value is not None and str(value).strip().replace('.','',1).isdigit(),(page_no,capacity,trade,loc,value)
     col=f"{trade} {loc}"; values[f"구분 {capacity}"][col]=str(value).strip(); cell_count+=1
  tables[f"p{page_no}-t0"]=values; transcribed[f"p{page_no}-t0"]={"floor":floor,"rows":values}
 assert cell_count==390
 pkg=json.loads(SPEC.read_text(encoding="utf8")); draft=pkg["draft"]
 for t in draft["tables"]:
  t["values"]=tables[t["id"]]; t["unit"]="인/대"
  t["role"]=f"{t['source'].split()[-1]} 냉각탑 capacity×trade×location crew rate"
 draft["quantity_model"]={"name":"per_unit","params":{"unit_rate_table":{"table":"p746-t0","table_selector":{"input":"building_floors","values":{"2층건물":"p746-t0","5층건물":"p747-t0","9층건물":"p748-t0"}},"row_input":"capacity","column_input":"install_location","trades":TRADES},"quantity_input":"quantity","surcharges":[],"note_adjustments":[]},"steps":["건물 층수에 해당하는 원문 표를 선택한다.","냉각탑 용량과 설치 위치에 따라 비계공·특별인부의 원문 품을 각각 조회한다.","각 직종의 단위 품에 냉각탑 대수를 곱한다."],"source":"PDF 인쇄 690~692쪽, 표 p746-t0/p747-t0/p748-t0","rounding":"정확한 유리수로 보존; 단위당 품은 공통 1-2-8·1-2-1 기본 자릿수 적용"}
 draft["work"]="냉각탑 설치"; draft["open_questions"]=["표 머리글에는 대당 기준 표기가 보이지 않아 품을 인/대, 입력 물량을 대로 해석했다. 해당 기준 단위의 명시 근거를 추가 확인해야 전체 규칙 검증으로 인정할 수 있다."]
 pkg["calc_type"]="per_unit"; pkg["calc_type_raw"]="per_unit"; pkg["calc_type_reason"]="건물 층수·용량·설치 위치별 직종 단위 품이 원문에 있어 per-unit 표 조회가 가능하다."
 pkg["citations"]=[]
 for table_id,info in transcribed.items():
  for row,cells in info["rows"].items():
   for col,val in cells.items(): pkg["citations"].append({"table_id":table_id,"row":row,"column":col,"value":val})
 pkg["citations"] += [{"chunk_id":"p748-x39","quote":"탑본체, 수조 등 부속기기의 반입 및 설치를 포함한 것이다."},{"chunk_id":"p748-x39","quote":"반입시 사용되는 장비의 사용료를 포함한 것이다."}]
 SPEC.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 lines=CHUNKS.read_text(encoding="utf8").splitlines(); by_id=set()
 for i,line in enumerate(lines):
  c=json.loads(line); tid=c.get("chunk_id")
  if tid not in tables: continue
  floor=transcribed[tid]["floor"]; body=[f"8-1-3 냉각탑 설치 | {floor}","구분 | 비계공·특별인부 × 설치 위치"]
  for row,cells in tables[tid].items(): body.append(" | ".join([row]+[f"{col} {value}" for col,value in cells.items()]))
  c["text"]="\n".join(body); c["structure"]="table"; c["issues"]=[]
  lines[i]=json.dumps(c,ensure_ascii=False,separators=(",",":")); by_id.add(tid)
 assert by_id==set(tables),by_id
 CHUNKS.write_text("\n".join(lines)+"\n",encoding="utf8")
 print(json.dumps({"status":"repaired","source_pages_printed":[690,691,692],"independent_grid_cells":cell_count,"tables":len(tables),"axis":"capacity rows × labor trade × installation-location columns","remaining_basis_question":True},ensure_ascii=False))
if __name__=="__main__": main()
