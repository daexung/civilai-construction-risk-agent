"""Focused smoke audit for existing formula specs after an opt-in output extension."""
from __future__ import annotations
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.rules.specs import load_specs
from backend.agent.tools.calc.daily_crew import _validate
from backend.agent.tools.calc.formula import _formula_field_applies,formula_quantity

def sample(field,inputs):
    kind=field.get('type'); allowed=field.get('allowed_values')
    if field.get('name')=='difficulty_factor':return '0.8'
    if kind=='enum' and isinstance(allowed,list):return allowed[0]
    if kind in ('positive_rational','positive_number','positive_integer','integer'):return '1'
    if kind in ('nonnegative_rational','nonnegative_number'):return '0'
    if kind=='boolean':return False
    if isinstance(allowed,list):return allowed[0]
    return '1'

results=[]
for ident,spec in load_specs().items():
    if spec.get('quantity_model',{}).get('name')!='formula':continue
    inputs={}
    for field in spec.get('inputs',[]):
        if _formula_field_applies(field,inputs):inputs[field['name']]=sample(field,inputs)
    result=formula_quantity(spec,inputs)
    results.append({'id':ident,'status':result.get('status'),'reason':result.get('reason'),
                    'line_count':len(result.get('unit_lines',[])),'sample_inputs':inputs})
out={'formula_specs_checked':len(results),'status_counts':{},'results':results,
     'scope':'smoke only; not full formula rule verification'}
for result in results:out['status_counts'][result['status']]=out['status_counts'].get(result['status'],0)+1
path=ROOT/'evals/runtime_validation/existing-formula-runtime-impact-2026-10-19.json'
path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'formula_specs_checked':len(results),'status_counts':out['status_counts'],
                  'noncomputed':[r for r in results if r['status']!='computed']},ensure_ascii=False,indent=2))
