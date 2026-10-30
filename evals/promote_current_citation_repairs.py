"""Incrementally reconcile four source-checked citation repairs."""
import hashlib,json,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TARGETS=[("건축","7-1-7"),("공통","7-4-1"),("기계설비","11-1-2"),("기계설비","5-4-1")]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
 chunks_path=ROOT/"data/processed/chunks.all.jsonl"; chunks=load_chunks(chunks_path); ch=sha(chunks_path); keys=[]; validations={}
 for div,sec in TARGETS:
  p=ROOT/"data/drafts/specs"/div/(sec+".json"); pkg=json.loads(p.read_text(encoding="utf8")); key=pkg["draft"]["id"]; keys.append(key)
  v=validate_one(p,ROOT/"data/drafts",chunks,ch); assert not v["format_issues"] and not v["citation_issues"],(key,v)
  validations["specs\\"+div+"\\"+sec+".json"]=(v,pkg)
 idxp=ROOT/"data/drafts/executable.json"; idx=json.loads(idxp.read_text(encoding="utf8"))
 # Summary counts in the old file lagged the actual active lists; use list cardinalities.
 assert len(idx["executable"])==748 and len(idx["failed"])==134
 for key in keys:
  f=next(x for x in idx["failed"] if x["id"]==key); assert f["stage"]=="format_or_input_preflight",f
 idx["failed"]=[x for x in idx["failed"] if x["id"] not in keys]; idx["executable"]=sorted(set(idx["executable"])|set(keys))
 idx["summary"]["executable"]=len(idx["executable"]); idx["summary"]["failed"]=len(idx["failed"])
 by=Counter()
 for p in (ROOT/"data/drafts/specs").rglob("*.json"):
  pkg=json.loads(p.read_text(encoding="utf8"))
  if pkg["draft"]["id"] in idx["executable"]: by[pkg.get("calc_type")]+=1
 for typ,n in by.items():
  if typ in idx["summary"]["by_calc_type"]: idx["summary"]["by_calc_type"][typ]["executable"]=n
 idx["summary"]["failure_reasons_top10"]=[list(x) for x in Counter(str(r.get("reason","")) for r in idx["failed"]).most_common(10)]
 idxp.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 rp=ROOT/"data/drafts/report.json"; report=json.loads(rp.read_text(encoding="utf8"))
 for item in report["results"]:
  if item["path"] not in validations: continue
  v,pkg=validations[item["path"]]; item["format_issues"]=v["format_issues"]; item["citation_issues"]=v["citation_issues"]; item["ok"]=True; item["open_questions"]=len(pkg.get("open_questions",[]))
 report["ok"]=sum(bool(x["ok"]) for x in report["results"]); report["with_format_issues"]=sum(bool(x["format_issues"]) for x in report["results"]); report["with_citation_issues"]=sum(bool(x["citation_issues"]) for x in report["results"]); report["total_open_questions"]=sum(x["open_questions"] for x in report["results"])
 rp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 specs=sorted((ROOT/"data/drafts/specs").rglob("*.json")); manifest=hashlib.sha256(b"\n".join(p.relative_to(ROOT/"data/drafts/specs").as_posix().encode()+b"\0"+sha(p).encode() for p in specs)).hexdigest()
 ev={"checkpoint":"incremental four-case source/citation repair","scope":"no full inventory replay","previous_active_lists":{"executable":748,"failed":134,"unsupported":174,"excluded":2},"current_active_lists":{"executable":len(idx["executable"]),"failed":len(idx["failed"]),"unsupported":174,"excluded":2,"failure_stages":dict(Counter(x["stage"] for x in idx["failed"]))},"promoted":keys,"source_checks":{"공통/7-4-1":"10 table cells; 4 independent daily-crew exact outputs","기계설비/5-4-1":"PDF printed p.677 visually checked, 16 cells, 8 exact rates; two dash cells kept as exclusions","기계설비/11-1-2":"52 rate/citation cells; 32 size/method routes, 22 calculated and 10 source-dash blocked; 16 priced offline labor costs; six percentage costs unpriced because crane wage is unavailable","건축/7-1-7":"prior focused source check reused; both slope branches rerun"},"validation":{"targeted_format_citation": "4/4 pass","all_rule_verification":0,"full_replay":False},"report_summary":{"ok":report["ok"],"with_format_issues":report["with_format_issues"],"with_citation_issues":report["with_citation_issues"]},"hashes":{"spec_count":len(specs),"spec_manifest_sha256":manifest,"chunks_sha256":sha(chunks_path),"executable_sha256":sha(idxp)}}
 out=ROOT/"evals/runtime_validation/incremental-source-citation-checkpoint-2026-10-19.json"; out.write_text(json.dumps(ev,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 print(json.dumps(ev,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
