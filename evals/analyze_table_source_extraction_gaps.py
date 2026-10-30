"""Compare saved failed-table matrices with numeric source-page text, for triage only."""
import json,re
from collections import Counter
from pathlib import Path
import pymupdf

ROOT=Path(__file__).resolve().parents[1]
INDEX=ROOT/"data/drafts/executable.json"
PDF=ROOT/"data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
OUT=ROOT/"evals/runtime_validation/active-table-source-extraction-gaps-2026-10-19.json"
NUM=re.compile(r"(?<![\w])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?(?![\w])")

def norm(x): return str(x).replace(",","").strip()

def main():
    idx=json.loads(INDEX.read_text(encoding="utf-8")); failures={x["id"]:x for x in idx["failed"]}
    root=json.loads((ROOT/"evals/runtime_validation/active-table-link-root-causes-2026-10-19.json").read_text(encoding="utf-8"))
    packages={}
    for p in (ROOT/"data/drafts/specs").rglob("*.json"):
        try: packages[json.loads(p.read_text(encoding="utf-8"))["draft"]["id"]]=p
        except Exception: pass
    doc=pymupdf.open(PDF); report=[]
    for c in root["candidates"]:
        d=json.loads(packages[c["failure_id"]].read_text(encoding="utf-8"))["draft"]
        refs=[]
        for t in d.get("tables",[]):
            tid=t["id"]; m=re.match(r"p(\d+)-t\d+",tid)
            if not m: continue
            page=int(m.group(1)); text=doc[page-1].get_text("text")
            values=t.get("values",{}); cells=[str(v).strip() for row in values.values() if isinstance(row,dict) for v in row.values()]
            numeric=[v for v in cells if NUM.fullmatch(v)]
            source_nums={norm(x) for x in NUM.findall(text)}
            matched=[v for v in numeric if norm(v) in source_nums]
            refs.append({"table_id":tid,"page":page,"source_page_chars":len(text),"printed_title":d.get("title"),"matrix_rows":len(values),"matrix_cells":len(cells),"numeric_cells":len(numeric),"numeric_cells_exactly_found_on_page":len(matched),"numeric_cell_source_match_ratio":round(len(matched)/len(numeric),3) if numeric else None,"source_numeric_token_count":len(source_nums),"role":t.get("role"),"structure":next((x.get("chunk_structure") for x in c["tables"] if x["table_id"]==tid),None)})
        report.append({"id":c["failure_id"],"division":c["division"],"section_no":c["section_no"],"class":c["class"],"root_cause_group":c["root_cause_group"],"diagnostic":failures[c["failure_id"]].get("reason"),"source_pages":refs})
    report.sort(key=lambda x:(sum(z["matrix_cells"] for z in x["source_pages"]),-sum(z["source_page_chars"] for z in x["source_pages"])))
    payload={"method":"read-only comparison of current candidate specs against PyMuPDF page text; numeric token overlap is triage evidence only and never proves row/column alignment","candidate_count":len(report),"classification_counts":dict(Counter(x["root_cause_group"] for x in report)),"candidates":report}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"candidates":len(report),"lowest_matrix_candidates":[{"section":x["section_no"],"group":x["root_cause_group"],"tables":x["source_pages"]} for x in report[:6]],"artifact":OUT.relative_to(ROOT).as_posix()},ensure_ascii=False,indent=2))
if __name__=="__main__": main()
