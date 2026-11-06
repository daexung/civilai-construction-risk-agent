"""5-1-8 source-grounded declaration and independently calculated labor route."""
import json, os, sys
from decimal import Decimal, ROUND_DOWN
from fractions import Fraction as F
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); os.environ["AGENT_OFFLINE"]="1"
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
from backend.agent.tools.calc.price import price_unit, select_rate_version

pkg=json.loads((ROOT/"data/drafts/specs/공통/5-1-8.json").read_text(encoding="utf-8")); spec=pkg["draft"]
# Independent source basis: PDF 160 table, printed p.104. 500㎡ / 120㎡/day.
source_days=F(500,120)
assert source_days==F(25,6)
expected_person_days={"철골공":F(25,3),"용접공":F(25,3),"보통인부":F(25,6)}
expected_wages={"철골공":255172,"용접공":286330,"보통인부":172698}
# Source-based 1-2-8 four-place per-unit rates, 1-2-2 line truncation to 0.1 won.
def trunc1(x): return (x*10//1)/10
line_amounts={trade:trunc1((F(count,120)*500)*wage) for trade,count,wage in [("철골공",2,255172),("용접공",2,286330),("보통인부",1,172698)]}
# Daily crew's declared line arithmetic uses the 4-place unit values from 1-2-8.
def source_round(value, places=4):
    scaled=value*(10**places); whole,rem=divmod(scaled.numerator,scaled.denominator)
    whole += (2*rem >= scaled.denominator)
    return Decimal(f"{whole//(10**places)}.{whole%(10**places):0{places}d}")
line_unit_quantities={trade:source_round(F(count,120)) for trade,count in [("철골공",2),("용접공",2),("보통인부",1)]}
line_unit_amounts={trade:(qty*Decimal(str(wage))).quantize(Decimal("0.1"),rounding=ROUND_DOWN) for (trade,qty),wage in zip(line_unit_quantities.items(),[255172,286330,172698])}
unit_labor=sum(line_unit_amounts.values())
unit_tools=(unit_labor*Decimal("0.03")).quantize(Decimal("0.1"),rounding=ROUND_DOWN)
expected_unit_total=int(unit_labor)+int(unit_tools)

def run(op, quantity):
    inputs={"operation":op,"quantity":str(quantity)}
    result=adjusted_daily_crew(spec,inputs)
    assert result["status"]=="computed",result
    priced=price_unit(spec,result["unit_lines"],select_rate_version("2026-11-01"),inputs,"2026-11-01")
    return result,priced

install, price500=run("설치",500)
assert F(install["work_days"])==source_days
assert {k:F(v) for k,v in install["person_days"].items()}==expected_person_days
assert F(install["equipment_days"]["크레인"])==F(25,6)
assert price500["status"]=="PARTIAL" and price500["unit_prices"]["노무비"]==str(int(unit_labor))
assert price500["unit_prices"]["경비"]==str(int(unit_tools))
assert int(price500["reference_amounts"]["total"])==expected_unit_total*500
assert any(x["name"]=="크레인" and "단가 자료 없음" in x["reason"] for x in price500["unpriced"])
# Installation vs removal use distinct source output cells. Same trades and one crane.
remove,price_remove=run("철거",500)
assert F(remove["work_days"])==F(50,17)
assert F(remove["person_days"]["철골공"])==F(100,17)
# 100→200 linear amount and stable unit rates; crane remains explicitly unpriced.
_,price100=run("설치",100)
_,price200=run("설치",200)
assert price100["unit_prices"]==price200["unit_prices"]==price500["unit_prices"]
assert int(price200["reference_amounts"]["total"])==2*int(price100["reference_amounts"]["total"])
print("PASS 5-1-8 source quantities and labor price; install 500m2 work_days=25/6, crew=25/3/25/3/25/6 person-days, crane=25/6 days")
print(f"PASS independent 1m2 labor+3% tools={expected_unit_total:,} KRW; 500m2 known subtotal={int(price500['reference_amounts']['total']):,} KRW; crane price explicitly unpriced")
print("PASS installation/removal source outputs and 100→200 quantity scaling; full estimate remains PARTIAL pending a registered, source-selected crane rate")
