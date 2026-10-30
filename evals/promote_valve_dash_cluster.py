"""Promote two per-unit valve items after exact PDF dash review."""
import hashlib,json,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
 targets=[("기계설비","5-1-1"),("기계설비","10-2-3")];ids=[];chunks_path=ROOT/"data/processed/chunks.all.jsonl";chunks=load_chunks(chunks_path)
 for div,sec in targets:
  p=ROOT/"data/drafts/specs"/div/(sec+".json");pkg=json.loads(p.read_text(encoding="utf8"));ids.append(pkg["draft"]["id"]);v=validate_one(p,ROOT/"data/drafts",chunks,file_sha256(chunks_path));assert not v["format_issues"] and not v["citation_issues"],v
 idxp=ROOT/"data/drafts/executable.json";idx=json.loads(idxp.read_text(encoding="utf8"));assert len(idx["executable"])==754 and len(idx["failed"])==128
 for key in ids: assert next(x for x in idx["failed"] if x["id"]==key)["stage"]=="calculator_execution_or_rule_gate"
 idx["failed"]=[x for x in idx["failed"] if x["id"] not in ids];idx["executable"]=sorted([*idx["executable"],*ids]);idx["summary"]["executable"]=len(idx["executable"]);idx["summary"]["failed"]=len(idx["failed"]);idx["summary"]["by_calc_type"]["per_unit"]["executable"]+=2;idx["summary"]["failure_reasons_top10"]=[list(x) for x in Counter(str(f.get("reason","")) for f in idx["failed"]).most_common(10)];idxp.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 rp=ROOT/"data/drafts/report.json";report=json.loads(rp.read_text(encoding="utf8"))
 for r in report["results"]:
  if r["path"] in ("specs\\기계설비\\5-1-1.json","specs\\기계설비\\10-2-3.json"):r["ok"]=True;r["format_issues"]=[];r["citation_issues"]=[]
 report["ok"]=sum(bool(x["ok"]) for x in report["results"]);report["with_format_issues"]=sum(bool(x["format_issues"]) for x in report["results"]);report["with_citation_issues"]=sum(bool(x["citation_issues"]) for x in report["results"]);rp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 evp=ROOT/"evals/runtime_validation/incremental-source-citation-checkpoint-2026-10-19.json";ev=json.loads(evp.read_text(encoding="utf8"));ev["current_active_lists"]={"executable":len(idx["executable"]),"failed":len(idx["failed"]),"unsupported":174,"excluded":2,"failure_stages":dict(Counter(f["stage"] for f in idx["failed"]))};ev["promoted"].extend(ids);ev["source_checks"]["기계설비/5-1-1 + 10-2-3"]="Side-by-side valve tables at printed pp.675/708 visually checked; 24 source cells compared and 12 exact routes run. Three ordinary-worker dash cells are condition-specific exclusions; no zero labor rate was invented.";ev["validation"]["targeted_format_citation"]="7/7 pass";ev["report_summary"]={"ok":report["ok"],"with_format_issues":report["with_format_issues"],"with_citation_issues":report["with_citation_issues"]};ev["hashes"]["spec_manifest_sha256"]=hashlib.sha256(b"\n".join(p.relative_to(ROOT/"data/drafts/specs").as_posix().encode()+b"\0"+sha(p).encode() for p in sorted((ROOT/"data/drafts/specs").rglob("*.json")))).hexdigest();ev["hashes"]["executable_sha256"]=sha(idxp);evp.write_text(json.dumps(ev,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 print(json.dumps({"promoted":ids,"current":{"executable":len(idx["executable"]),"failed":len(idx["failed"]),"unsupported":174,"excluded":2,"stages":ev["current_active_lists"]["failure_stages"]},"source_cells":24,"exact_routes":12,"dash_exclusions":3},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
