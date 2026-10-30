"""Verify 9-7-3's one-district source basis and preserve unresolved coefficients."""
import hashlib,json,re,sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from pipeline.validate_drafts import DEFAULT_CHUNKS,DEFAULT_DRAFTS_DIR,file_sha256,load_chunks,validate_one
SPEC=ROOT/'data/drafts/specs/토목/9-7-3.json';IMAGE0=ROOT/'evals/runtime_validation/source-p584-9-7-3.png';IMAGE1=ROOT/'evals/runtime_validation/source-p585-9-7-3.png';AUDIT=ROOT/'evals/runtime_validation/civil-9-7-3-district-basis-audit-2026-10-19.json'
TRADES=('지적기사','지적산업기사','지적기능사');TOTAL={'지적기사':'94.45','지적산업기사':'188.65','지적기능사':'31.00'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 spec=json.loads(SPEC.read_text(encoding='utf-8'))['draft'];table=spec['tables'][0]['values'];cells=[];sums={t:Fraction(0) for t in TRADES}
 for row,columns in table.items():
  if row.startswith('소계') or row=='합계':continue
  for trade,raw in columns.items():
   value=Fraction(re.search(r'\d+(?:\.\d+)?',raw).group());sums[trade]+=value;cells.append({'row':row,'trade':trade,'source_value':raw,'numeric_value':str(value)})
 assert sums=={k:Fraction(v) for k,v in TOTAL.items()},(sums,TOTAL)
 assert {k:table['합계'][k] for k in TRADES}==TOTAL
 area=spec['tables'][1]['values']['계수'];assert list(area.values())==['1.0','0.9','0.8','0.7','0.6','0.5']
 parcel=spec['tables'][2]['values']['계수'];assert list(parcel.values())==['1.00','1.05','1.10','1.15','1.20','1.25','1.05×n']
 base={'area':'200000','parcel_count':'50','is_continuous':True,'include_stake_out':True,'district_count':'1'}
 result=per_unit(spec,base);assert result['status']=='computed',result;rates={x['name']:Fraction(x['exact']) for x in result['unit_lines']};assert rates=={k:Fraction(v) for k,v in TOTAL.items()}
 assert all(line['unit']=='인/지구' and any(c.get('internal_id')=='p584-t0' for c in line['citations']) for line in result['unit_lines'])
 noncontinuous=per_unit(spec,{**base,'area':'250000','is_continuous':False});assert noncontinuous['status']=='computed',noncontinuous
 over_area=per_unit(spec,{**base,'area':'250000','is_continuous':True});assert over_area['status']=='blocked',over_area
 over_parcels=per_unit(spec,{**base,'parcel_count':'51'});assert over_parcels['status']=='blocked',over_parcels
 no_stakeout=per_unit(spec,{**base,'include_stake_out':False});assert no_stakeout['status']=='blocked',no_stakeout
 validator=validate_one(SPEC.resolve(),DEFAULT_DRAFTS_DIR.resolve(),load_chunks(DEFAULT_CHUNKS),file_sha256(DEFAULT_CHUNKS));assert validator['ok'],validator
 audit={'id':spec['id'],'status':'district_basis_and_source_totals_verified_with_policy_gates','source':{'physical_pages':[584,585],'printed_pages':[528,529],'images':['evals/runtime_validation/source-p584-9-7-3.png','evals/runtime_validation/source-p585-9-7-3.png'],'image_sha256':[sha(IMAGE0),sha(IMAGE1)],'visual_review':True,'task_cells':cells,'task_cell_count':len(cells),'independent_total':{k:str(v) for k,v in sums.items()},'area_coefficient_cells':area,'parcel_coefficient_cells':parcel},'runtime':{'quantity_basis':'one district; output unit is 인/지구, downstream quantity is district_count','baseline_routes':1,'noncontinuous_over_200000':'computed without coefficient, per source exception','continuous_over_200000':'blocked pending row-by-row diminished-coefficient aggregation','over_50_parcels':'blocked pending upper-end interval formula','without_stakeout':'blocked pending exact row exclusion route','validator':validator,'full_rule_verification':False},'spec_sha256':sha(SPEC),'per_unit_sha256':sha(ROOT/'backend/agent/tools/calc/per_unit.py')}
 AUDIT.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'task_cells':len(cells),'district_rates':{k:str(v) for k,v in sums.items()},'baseline':result['status'],'policy_gates':3,'validator':validator['ok']}))
if __name__=='__main__':main()
