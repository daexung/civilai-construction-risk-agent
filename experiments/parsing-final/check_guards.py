import copy
import json
import sys
import tempfile
from pathlib import Path
sys.dont_write_bytecode=True
WORK=Path(__file__).resolve().parent;sys.path.insert(0,str(WORK));import run
import assemble
results=[]
def check(name,ok):results.append({'name':name,'passed':bool(ok)})
def table(rows, spans=None):
    cells=[]
    for r,row in enumerate(rows):
        for c,text in enumerate(row):
            if text is None:continue
            span=(spans or {}).get((r,c),1)
            cells.append({'r0':r,'r1':r+1,'c0':c,'c1':c+span,'text':text,
                          'bbox_pt':[c*100,r*30,(c+span)*100,(r+1)*30]})
    return {'n_rows':len(rows),'n_cols':len(rows[0]),'cells':cells}
def texts(t):return [x['text'] for x in assemble.table_to_records(t,[],'시험',1,trace=True)]
reference=table([['N(㎏)','40','50'],['보정치(a)','1.06','1.03']])
check('숫자 머리글이 계수에 연결됨',assemble.header_of(reference,[])==(1,'단위 제목과 계수 행 경계') and '40 1.06' in texts(reference)[0])
body=table([['N(㎏)','40','50'],['철골공','1','2'],['다른 항목','3','4']])
check('일반 숫자 본문을 머리글로 올리지 않음',assemble.header_of(body,[])[0]==0)
shaded=table([['N(㎏)','조건 A','조건 B'],['직종','40','50'],['보정치(a)','1','2']])
check('명시적 음영 머리글 우선',assemble.header_of(shaded,[(0,0,300,60)])[0]==2)
categorical=table([['자재','바탕 A','바탕 B'],['정배지','전면붙임',None]],{(1,1):2})
check('짧은 공동 조건은 열 이름 유지',any('바탕 A 전면붙임' in s and '바탕 B 전면붙임' in s for s in texts(categorical)))
prose=table([['구분','단위','수량'],['산출기준','재료량은 설계에 따라 별도 계상한다.',None]],{(1,1):2})
check('병합 설명을 수량으로 복제하지 않음',any('산출기준' in s and '수량 재료량' not in s for s in texts(prose)))
remark=table([['구분','단위','수량'],['비고','- 작업 A를 포함한다.\n- 작업 B는 별도 계상한다.',None]],{(1,1):2})
check('기존 비고 문장 분리 유지',len(texts(remark))==2)
keyvalue=table([['항목','1-4-1 관 접합\n4-2-1 송풍기 설치']])
check('한 행 목록 전체가 머리글로 사라지지 않음',assemble.header_of(keyvalue,[])[0]==0 and bool(texts(keyvalue)))
m=run.read(run.CORRECTIONS)
with tempfile.TemporaryDirectory(dir=run.OUT) as td:
    assert Path(td).resolve().is_relative_to(WORK.resolve())
    p=Path(td)/'bad.json';bad=copy.deepcopy(m);bad['pdf_sha256']='0'*64;run.write(p,bad)
    try:run.sc.apply({'kids':[]},run.RAW,run.PDF,p);rejected=False
    except ValueError:rejected=True
    check('다른 문서 해시의 교정 거부',rejected)
    bad=copy.deepcopy(m);bad['cells'][0]['expected_text']='wrong';run.write(p,bad)
    doc=run.read(run.RAW)
    try:run.sc.apply(doc,run.RAW,run.PDF,p);rejected=False
    except ValueError:rejected=True
    check('원래 칸 내용이 다르면 교정 거부',rejected)
run.write(run.OUT/'guard_checks.json',{'checks':results,'failed':sum(not x['passed'] for x in results)})
print(json.dumps(results,ensure_ascii=False))
sys.exit(1 if any(not x['passed'] for x in results) else 0)
