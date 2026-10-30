"""Restore 13-1-2's four flattened rate matrices from the source PDF table grids."""
import hashlib,json
from pathlib import Path
import pymupdf
ROOT=Path(__file__).resolve().parents[1]
SPEC=ROOT/"data/drafts/specs/기계설비/13-1-2.json"
PDF=ROOT/"data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
SNAP=ROOT/"evals/runtime_validation/13-1-2-pre-restoration-spec-tables-2026-10-19.json"
CHUNKS=ROOT/"data/processed/chunks.all.jsonl"
CHUNK_SNAP=ROOT/"evals/runtime_validation/13-1-2-pre-restoration-source-chunks-2026-10-19.json"
SIZES=["ø25","32","40","50","65","80","90","100","125","150","200","250","300","350","400","450","500","600"]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def forward(values):
 out=[];current=""
 for v in values:
  if v is not None and str(v).strip():current=" ".join(str(v).split())
  out.append(current)
 return out
def grid(page_index,table_index,table_id,row_sizes,unit="인/개",source=None,start_column=2):
 table=pymupdf.open(PDF)[page_index].find_tables().tables[table_index]; rows=table.extract();assert len(rows)==4,(page_index,table_index,len(rows))
 groups,schs=forward(rows[0]),forward(rows[1]); trades=forward(rows[2]); cells=rows[3]
 vals={}
 for j in range(start_column,len(cells)):
  group,sch,trade=groups[j],schs[j],trades[j]
  if not group or not sch or not trade:continue
  key=f"{group} | {sch} | {trade}"
  seq=[" ".join(x.split()) for x in (cells[j] or "").splitlines() if x.strip()]
  assert len(seq)<=len(row_sizes),(table_id,j,len(seq),len(row_sizes))
  for size,value in zip(row_sizes,seq): vals.setdefault(size,{})[key]=value
 return {"id":table_id,"role":"13-1-2 관만곡 다단 머리글 단위당 품","source":source or f"PDF {page_index+1-55}쪽 원문 다단 표","unit":unit,"values":vals,"cite":{"table_id":table_id}}
def main():
 package=json.loads(SPEC.read_text(encoding="utf-8"));draft=package["draft"]
 if not SNAP.exists():SNAP.write_text(json.dumps({"spec_sha256_before":sha(SPEC),"tables_before":draft["tables"]},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 matrix=[
  grid(787,0,"p788-t0",SIZES,source="PDF 732쪽 첫 번째 다단 표"),
  grid(787,1,"p788-t1",SIZES[:12],source="PDF 732쪽 (개당) 이어지는 다단 표; 관경 25~250",start_column=0),
  grid(788,0,"p789-t0",SIZES[12:16],source="PDF 733쪽 (개당) 앞 표 이어짐; 관경 300~450",start_column=0),
  grid(788,1,"p789-t1",SIZES[:15],source="PDF 733쪽 U곡관 및 2편심 U곡관 표; 관경 25~400"),
 ]
 old={t["id"]:t for t in draft["tables"]}
 for table in matrix:old[table["id"]]=table
 draft["tables"]=[old[k] for k in ("p788-t0","p788-t1","p789-t0","p789-t1","p789-t2") if k in old]
 rate=draft["quantity_model"]["params"]["unit_rate_table"]
 rate.update({"table":"p788-t0","row_input":"pipe_diameter","column_input":None,"trades":["플랜트배관공","특별인부"],"trade_in_columns":True,"trade_column_selector":{"input":"bend_type","contains":["{value}","{trade}"],"exact_component_inputs":["sch_no"]},"row_value_map":{"25":"ø25"}})
 # Route each declared diameter/bend/SCH combination only to the source matrix that actually contains both trade cells.
 routes=[];dash_rules=[];all_values={}
 for t in matrix:
  for size,columns in t["values"].items():
   for col,raw in columns.items():
    parts=[x.strip() for x in col.split("|")];assert len(parts)==3,(t["id"],col)
    bend,sch,trade=parts;key=(size.removeprefix("ø"),bend,sch)
    all_values.setdefault(key,{})[trade]=raw
 for (diameter,bend,sch),trade_values in sorted(all_values.items(),key=lambda x:(SIZES.index("ø"+x[0][0]) if "ø"+x[0][0] in SIZES else SIZES.index(x[0][0]),x[0][1],x[0][2])):
  if not any(v!="-" for v in trade_values.values()):continue
  if len(trade_values)!=2:continue  # Missing source cells remain unresolved, never inferred as zero/dash.
  source_row="ø25" if diameter=="25" else diameter
  source_table=next(t["id"] for t in matrix if source_row in t["values"] and all(t["values"][source_row].get(f"{bend} | {sch} | {trade}")==value for trade,value in trade_values.items()))
  routes.append({"when":{"pipe_diameter":diameter,"bend_type":bend,"sch_no":sch},"table":source_table})
  for trade,raw in trade_values.items():
   if raw=="-":
    dash_rules.append({"trade":trade,"when":{"pipe_diameter":diameter,"bend_type":bend,"sch_no":sch},"source":"원문 표의 명시적 대시; 해당 직종 품 없음","cite":{"table_id":source_table,"row":diameter if diameter!="25" else "ø25","column":trade,"value":"-"}})
 rate["table_selector"]={"routes":routes}
 draft["quantity_model"]["params"]["excluded_resources"]=dash_rules
 package["draft"]=draft;SPEC.write_text(json.dumps(package,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 chunk_list=[json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
 targets={t["id"]:t for t in matrix};before=[c for c in chunk_list if c.get("chunk_id") in targets]
 if not CHUNK_SNAP.exists():CHUNK_SNAP.write_text(json.dumps({"chunks_sha256_before":sha(CHUNKS),"chunks":before},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 provenance={"p788-t0":"explicit size column on printed p.732","p788-t1":"size rows continued from p.732 top matrix; row order checked against the p.732 diameter sequence","p789-t0":"four row labels 300, 350, 400, 450 continue the p.732 lower matrix; row order checked against the p.733 page image","p789-t1":"explicit size column on printed p.733"}
 for chunk in chunk_list:
  tid=chunk.get("chunk_id")
  if tid not in targets:continue
  table=targets[tid];body=["13-1-2 관만곡(Pipe Bending) 설치",f"복원된 다단 머리글 표: {table['source']}",f"행 축: 관경(㎜); {provenance[tid]}"]
  body.extend(f"{row} | {column} | {value}" for row,cols in table["values"].items() for column,value in cols.items())
  chunk["text"]="\n".join(body);chunk["extraction_recovery"]={"method":"PyMuPDF table grid with stacked cell values split in source order; page images visually checked","row_axis_evidence":provenance[tid],"source_table_id":tid}
 CHUNKS.write_text("\n".join(json.dumps(c,ensure_ascii=False) for c in chunk_list)+"\n",encoding="utf-8")
 print(json.dumps({"tables":[{"id":t["id"],"rows":len(t["values"]),"cells":sum(len(v) for v in t["values"].values())} for t in matrix],"routes":len(routes),"dash_exclusions":len(dash_rules),"spec_sha256":sha(SPEC)},ensure_ascii=False))
if __name__=="__main__":main()
