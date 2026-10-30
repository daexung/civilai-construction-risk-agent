import json, sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit
SPEC=json.loads((ROOT/"data/drafts/specs/토목/9-4-3.json").read_text(encoding="utf-8"))["draft"]
EXPECTED={"작업계획 및 준비":{"특급기술자":"0.5","고급기술자":"1.1"},"객체추출 및 묘사":{"특급기술자":"1.0","고급기술자":"3.0","중급기술자":"8.0","초급기술자":"8.0"},"현황측량 및 조사":{"고급기술자":"1.0","중급기술자":"6.0","초급기술자":"3.0"},"정위치 편집":{"고급기술자":"0.8","중급기술자":"1.2","초급기술자":"2.0"},"구조화 편집":{"고급기술자":"1.6","중급기술자":"4.0","초급기술자":"2.4"},"정리 및 점검":{"특급기술자":"0.2","고급기술자":"0.8","중급기술자":"0.6"}}
def run(length,terrain="그 외 지역",source="MMS측량"):
 return per_unit(SPEC,{"length":str(length),"terrain_type":terrain,"source_type":source},labor_only=True)
def check(cond,label):
 print(("PASS" if cond else "FAIL")+" "+label)
 if not cond: raise SystemExit(1)
# Independent source cell comparison against the transcription above.
actual=SPEC["tables"][0]["values"]
check({r:{t:v.strip("()") for t,v in cols.items()} for r,cols in actual.items()}==EXPECTED,"18 independently transcribed p.513 labor cells")
for terrain,factor in [("그 외 지역",Fraction(1)),("시가지",Fraction(13,10)),("밀집시가지",Fraction(17,10))]:
 result=run(10,terrain)
 check(result.get("status")=="computed",f"execution {terrain}: {result.get('reason')}")
 lines=result["unit_lines"]
 check(len(lines)==18,f"18 route lines {terrain}")
 total=sum(Fraction(line["exact"]) for line in lines)
 expected=Fraction(452,100)+(factor-1)*Fraction(42,10)
 # terrain-applicable rows independently total 37.9 person-days / 10km.
 check(total==expected,f"independent per-km terrain arithmetic {terrain}: {total} == {expected}")
 if terrain=="그 외 지역":
  check(sum(Fraction(x["exact"]) for x in lines if x["name"]=="특급기술자")==Fraction(17,100),"special engineer 0.17 person-day/km")
  check(sum(Fraction(x["exact"]) for x in lines if x["name"]=="고급기술자")==Fraction(83,100),"senior engineer 0.83 person-day/km")
  check(sum(Fraction(x["exact"]) for x in lines if x["name"]=="중급기술자")==Fraction(198,100),"intermediate engineer 1.98 person-day/km")
  check(sum(Fraction(x["exact"]) for x in lines if x["name"]=="초급기술자")==Fraction(154,100),"junior engineer 1.54 person-day/km")
short=run("0.5")
check(short.get("status")=="computed","minimum 1km execution")
check(all(Fraction(x.get("quantity_factor","1"))==2 for x in short["unit_lines"]),"0.5km lines scale to source minimum 1km")
one=run("1")
check(one.get("status")=="computed" and all(Fraction(x.get("quantity_factor","1"))==1 for x in one["unit_lines"]),"1km boundary")
long=run("1.1")
check(long.get("status")=="computed" and all(Fraction(x.get("quantity_factor","1"))==1 for x in long["unit_lines"]),"over-1km is not floored")
for source in ["현황측량","기존 도로대장","기존 디지털 도로대장"]:
 r=run(10,source=source)
 check(r.get("status")=="blocked",f"non-MMS source blocked: {source}")
check(all(line.get("citations") for line in short["unit_lines"]),"source citations present on every route")
print("9-4-3 focused source/rule audit passed")
