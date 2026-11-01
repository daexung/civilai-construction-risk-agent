"""Source-based formula and hourly machine pricing check for 8-2-6."""
import json,sys
from fractions import Fraction as F
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.formula import formula_quantity
from backend.agent.tools.calc.price import price_unit,select_rate_version
spec=json.load(open(ROOT/'data/drafts/specs/공통/8-2-6.json',encoding='utf-8'))['draft']
def inputs(qty='100',basis='natural'):
 f={x['name']:x for x in spec['inputs']}
 soil=f['soil_condition']['allowed_values'][0];site=f['site_condition']['allowed_values'][0];road=f['road_condition']['allowed_values'][0]
 return {'soil_condition':soil,'site_condition':site,'road_condition':road,'push_dozer_used':False,'has_large_cobble':False,'L1':'120','L2':'180','machine_spec':'5.4','volume_basis':f['volume_basis']['allowed_values'][0] if basis=='natural' else f['volume_basis']['allowed_values'][1],**({'L':'1.2'} if basis=='natural' else {}),'quantity':qty,'fuel_price':'1000'}
version=select_rate_version('2026-06-01')
def main():
 i100=inputs('100');r100=formula_quantity(spec,i100);assert r100['status']=='computed',r100
 q=F(60)*F('5.4')*F('1.13')*F(1,F('1.2'))*F('.85')/(F(120,400)+F(180,600)+F('2.8'))
 lines={x['name']:x for x in r100['unit_lines'] if x['kind']=='equipment' or x['kind']=='reference'}
 eq=next(x for x in r100['unit_lines'] if x['kind']=='equipment');ref=next(x for x in r100['unit_lines'] if x['kind']=='reference')
 assert F(ref['exact'])==q and F(eq['exact'])==1/q,(ref,eq,q)
 p100=price_unit(spec,r100['unit_lines'],version,i100,'2026-06-01');assert p100['status']=='OK' and not p100['unpriced'],p100
 i200=inputs('200');r200=formula_quantity(spec,i200);eq200=next(x for x in r200['unit_lines'] if x['kind']=='equipment');ref200=next(x for x in r200['unit_lines'] if x['kind']=='reference')
 p200=price_unit(spec,r200['unit_lines'],version,i200,'2026-06-01')
 assert F(ref200['exact'])==q and F(eq200['exact'])==F(eq['exact'])
 assert p200['total']==p100['total'] and p200['unit_prices']==p100['unit_prices'],(p100['total'],p200['total'],p100['unit_prices'],p200['unit_prices'])
 loose=inputs('100',basis='loose');assert formula_quantity(spec,loose)['status']=='computed'
 blocked=inputs('100');blocked['has_large_cobble']=True;assert formula_quantity(spec,blocked)['status']=='blocked'
 pusher=inputs('100');pusher['push_dozer_used']=True;pr=formula_quantity(spec,pusher);assert pr['status']=='computed';qp=F(60)*F('5.4')*F('1.13')*F(1,F('1.2'))*F('.85')/(F(120,400)+F(180,600)+F('1.6'));assert F(next(x['exact'] for x in pr['unit_lines'] if x['kind']=='reference'))==qp
 pp=price_unit(spec,pr['unit_lines'],version,pusher,'2026-06-01');assert pp['status']=='PARTIAL' and any('푸쉬도우저' in x['name'] for x in pp['unpriced'])
 print('PASS Q=60*q*f*E/cm=',q,'hours100=',eq['exact'],'unit_price=',p100['total'],'unit_price200=',p200['total'],'loose basis, cobble block, push-dozer Q and PARTIAL cost')
if __name__=='__main__':main()
