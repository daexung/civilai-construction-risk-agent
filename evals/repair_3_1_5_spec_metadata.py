"""Align 3-1-5 package metadata/citations with its restored source table."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from promote_unsupported_specs import refresh_table_citations
from pipeline.validate_drafts import load_chunks,validate_one
PATH=ROOT/"data/drafts/specs/유지관리/3-1-5.json"
CHUNKS=ROOT/"data/processed/chunks.all.jsonl"
package=json.loads(PATH.read_text(encoding="utf8"))
package["calc_type"]="per_unit"
package["calc_type_reason"]="원문 표의 공종별 인력 단위당 품과 작업 종류별 ㎡/㎥ 분모가 명시되어 있어 기존 per_unit 계산기로 표현한다."
package["open_questions"]=["잡재료는 인력품의 5% 이내로만 제시되어 확정률 없이 적용하지 않고 검토 대상으로 유지한다."]
package["questions"]=["잡재료를 인력품의 5% 이내에서 적용할 비율은 별도 검토가 필요합니다."]
missing=refresh_table_citations(package,"p969-t0")
assert not missing,missing
if package.get("meta"):
    package["meta"]["chunks_sha256"]=hashlib.sha256(CHUNKS.read_bytes()).hexdigest()
PATH.write_text(json.dumps(package,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
chunks=load_chunks(CHUNKS)
result=validate_one(PATH,ROOT/"data/drafts/specs",chunks,None)
assert result["ok"],result
print(json.dumps({"id":package["draft"]["id"],"calc_type":package["calc_type"],"table_citations":8,"validation":{"ok":result["ok"],"format_issues":result["format_issues"],"citation_issues":result["citation_issues"]}},ensure_ascii=False))
