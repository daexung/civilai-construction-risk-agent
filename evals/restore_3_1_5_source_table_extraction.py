"""Restore the visually transcribed 3-1-5 table in its damaged source chunk."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CHUNKS=ROOT/"data/processed/chunks.all.jsonl"
PDF=ROOT/"data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
IMAGE=ROOT/"evals/runtime_validation/source-p969-3-1-5-table-zoom.png"
AUDIT=ROOT/"evals/runtime_validation/source-extraction-3-1-5-restoration-2026-10-19.json"
EXPECTED_OLD="3-1-5 석축 헐기(인력)('22년 보완)\n구분 | 단위 ㎡당\n구분 | 단위 ㎥당 | 할석공(인) 0.1"
RESTORED=("3-1-5 석축 헐기(인력)('22년 보완)\n"
 "구분 | 단위 | 할석공(인) | 보통인부(인)\n"
 "메쌓기 뒷길이 45∼60㎝ | ㎡당 | - | 0.2\n"
 "메쌓기 뒷길이 60∼90㎝ | ㎡당 | - | 0.3\n"
 "찰쌓기 | ㎡당 | - | 0.6\n"
 "절석 (마름돌) 쌓기 | ㎥당 | 0.1 | 1.1")
def sha(data):return hashlib.sha256(data).hexdigest()
def main():
 raw=CHUNKS.read_bytes(); lines=raw.splitlines(keepends=True);found=0;updated=[]
 for line in lines:
  item=json.loads(line)
  if item.get("chunk_id")=="p969-t0":
   found+=1
   if item.get("text")==EXPECTED_OLD:
    assert item.get("uncertain_record_ids")==[20118,20119]
    item["text"]=RESTORED;item["structure"]="ok";item["uncertain_record_ids"]=[]
   else:
    assert item.get("text")==RESTORED and item.get("structure")=="ok",item
   line=(json.dumps(item,ensure_ascii=False,separators=(",",":"))+"\n").encode("utf8")
  updated.append(line)
 assert found==1
 new=b"".join(updated)
 if new!=raw:CHUNKS.write_bytes(new)
 report={"chunk_id":"p969-t0","status":"original_source_table_extraction_restored","source":{"physical_page":969,"printed_page":913,"pdf_sha256":sha(PDF.read_bytes()),"visual_image":str(IMAGE.relative_to(ROOT)),"image_sha256":sha(IMAGE.read_bytes()),"visually_checked_cells":8},"restored_text":RESTORED,"uncertain_record_ids_before":[20118,20119],"uncertain_record_ids_after":[],"before_chunks_sha256":sha(raw),"after_chunks_sha256":sha(new),"changed":new!=raw}
 AUDIT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 print(json.dumps({"chunk":"p969-t0","changed":report["changed"],"cells":8,"audit":str(AUDIT.relative_to(ROOT))},ensure_ascii=False))
if __name__=="__main__":main()
