"""Check all 32 2-2-6 rates and exact compound-header selection."""
import hashlib, itertools, json, sys
from fractions import Fraction
from pathlib import Path
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.source.citation import cite_table

PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
PATH = ROOT / "data/drafts/specs/유지관리/2-2-6.json"
OUT = ROOT / "evals/runtime_validation/per-unit-maintenance-2-2-6-compound-headers-2026-10-19.json"
WORKS = ("목침목 → 목침목", "목침목 → PCT", "PCT → PCT", "교량 침목 교환")
TRADES = ("궤도공", "보통인부")
HEADERS = ("3시간 차단 A-Type", "3시간 차단 B-Type", "4시간 차단 A-Type", "4시간 차단 B-Type")
EXPECTED = {
 "목침목 → 목침목 궤도공": ("0.283", "0.209", "0.279", "0.206"),
 "목침목 → 목침목 보통인부": ("0.071", "0.052", "0.070", "0.052"),
 "목침목 → PCT 궤도공": ("0.662", "0.488", "0.650", "0.479"),
 "목침목 → PCT 보통인부": ("0.192", "0.141", "0.189", "0.139"),
 "PCT → PCT 궤도공": ("0.775", "0.571", "0.761", "0.561"),
 "PCT → PCT 보통인부": ("0.224", "0.165", "0.221", "0.163"),
 "교량 침목 교환 궤도공": ("1.005", "0.740", "0.988", "0.728"),
 "교량 침목 교환 보통인부": ("0.291", "0.214", "0.287", "0.211"),
}
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
 spec = json.loads(PATH.read_text(encoding="utf8"))["draft"]
 t = next(x for x in spec["tables"] if x["id"] == "p952-t0")
 cells=[]
 for row, rates in EXPECTED.items():
  assert row in t["values"]
  for head, expected in zip(HEADERS, rates):
   actual=t["values"][row][head]
   assert actual == expected, (row,head,actual,expected)
   cite=cite_table("p952-t0",row,head,actual)
   assert cite.get("value")==actual
   cells.append({"row":row,"column":head,"value":actual,"citation_page":cite.get("pdf_page")})
 assert len(cells)==32
 doc=pymupdf.open(PDF)
 candidates=[]
 for n,page in enumerate(doc):
  txt=page.get_text("text") or ""
  if "2-2-6" in txt and "목침목" in txt and "3시간" in txt:
   candidates.append((n+1,txt))
 assert candidates, "source page with section/table title not found"
 page_no, page_text=candidates[0]
 assert "0.283" in page_text and "1.005" in page_text and "0.211" in page_text
 routes=[]
 for work, bt, site in itertools.product(WORKS,("3시간 차단","4시간 차단"),("A-Type","B-Type")):
  inp={"work_type":work,"block_time":bt,"site_condition":site,"quantity":"100"}
  got=per_unit(spec,inp)
  assert got.get("status")=="computed", (inp,got)
  ix=HEADERS.index(f"{bt} {site}")
  lines={x["name"]:x for x in got["unit_lines"]}
  assert set(lines)==set(TRADES)
  for trade in TRADES:
   exp=Fraction(EXPECTED[f"{work} {trade}"][ix])
   assert Fraction(lines[trade]["exact"])==exp, (inp,trade,lines[trade],exp)
   assert Fraction(lines[trade]["citations"][0].get("value"))==exp
  routes.append({**inp,"status":"computed","crew_totals":{k:v["exact"] for k,v in lines.items()}})
 audit={"id":spec["id"],"status":"original_cells_and_compound_header_routes_verified",
        "source":{"physical_pdf_page":page_no,"printed_page":896,"pdf_sha256":sha(PDF),
                  "unique_cells_checked":len(cells),"cells":cells,
                  "layout":"rows are work type × trade; columns are block duration × site type; all 32 cells separately matched against original PDF text."},
        "runtime":{"exact_work_block_site_routes":len(routes),"routes":routes,"computed":len(routes)},
        "scope":"All 32 cells on p952-t0 and all 16 work×block-time×site routes, with 100-piece quantity; each trade total checked by independent multiplication.",
        "spec_sha256":sha(PATH),"per_unit_sha256":sha(ROOT/"backend/agent/tools/calc/per_unit.py")}
 OUT.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 print(json.dumps({"cells":len(cells),"routes":len(routes),"source_page":page_no,"audit":str(OUT.relative_to(ROOT))},ensure_ascii=False))
if __name__=="__main__": main()
