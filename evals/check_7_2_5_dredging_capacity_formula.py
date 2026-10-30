"""Independent PDF-cell, worst-efficiency formula, route and citation audit for 7-2-5."""
import hashlib,itertools,json,sys
from pathlib import Path
from fractions import Fraction
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.formula import formula_quantity
from pipeline.validate_drafts import DEFAULT_CHUNKS,DEFAULT_DRAFTS_DIR,file_sha256,load_chunks,validate_one
spec=json.loads((ROOT/'data/drafts/specs/토목/7-2-5.json').read_text(encoding='utf8'))['draft']
areas={'기초고르기':'1.6','피복석고르기':'3.5','피복석거친고르기':'3.8','내부사석고르기':'3.8','필터사석고르기':'8.4'}
eff={
 '0~15m':{'천후|조용할때':'0.75','천후|풍랑':'0.64','조류|0~2.8km/hr':'0.75','조류|2.8~5.5km/hr':'0.53','명암|보통':'0.75','명암|흐릴때':'0.49'},
 '15~20m':{'천후|조용할때':'0.57','천후|풍랑':'0.48','조류|0~2.8km/hr':'0.57','조류|2.8~5.5km/hr':'0.40','명암|보통':'0.57','명암|흐릴때':'0.37'},
 '20~25m':{'천후|조용할때':'0.41','천후|풍랑':'0.35','조류|0~2.8km/hr':'0.41','조류|2.8~5.5km/hr':'0.29','명암|보통':'0.41','명암|흐릴때':'0.27'},
 '25~30m':{'천후|조용할때':'0.35','천후|풍랑':'0.30','조류|0~2.8km/hr':'0.35','조류|2.8~5.5km/hr':'0.25','명암|보통':'0.35','명암|흐릴때':'0.23'}}
assert spec['tables'][0]['values']['표준고르기면적(a)']==areas
assert spec['tables'][1]['values']==eff
routes=0;worst_counts={'tide':0,'current':0,'visibility':0,'schedule_override':0}
for work,depth,tide,current,visibility,days in itertools.product(areas,eff,('천후|조용할때','천후|풍랑'),('조류|0~2.8km/hr','조류|2.8~5.5km/hr'),('명암|보통','명암|흐릴때'),(False,True)):
    candidates={'tide':Fraction('1.00') if days else Fraction(eff[depth][tide]),'current':Fraction(eff[depth][current]),'visibility':Fraction(eff[depth][visibility])}
    worst=min(candidates.values());expected=Fraction(areas[work])*worst
    result=formula_quantity(spec,{'gorgi_type':work,'depth_band':depth,'tide_condition':tide,'current_speed':current,'visibility':visibility,'monthly_workdays_20plus':days})
    assert result['status']=='computed',(work,depth,tide,current,visibility,days,result)
    line=result['unit_lines'][0];assert Fraction(line['exact'])==expected and line['unit']=='m²/hr',(line,expected)
    assert all(any(c.get('internal_id')==tid for c in line['citations']) for tid in ('p447-t0','p447-t1'))
    if days:
        assert any(c.get('internal_id')=='p447-x11' for c in line['citations'])
        worst_counts['schedule_override']+=1
    elif candidates['tide']==worst:worst_counts['tide']+=1
    elif candidates['current']==worst:worst_counts['current']+=1
    else:worst_counts['visibility']+=1
    routes+=1
validator=validate_one((ROOT/'data/drafts/specs/토목/7-2-5.json').resolve(),DEFAULT_DRAFTS_DIR.resolve(),load_chunks(DEFAULT_CHUNKS),file_sha256(DEFAULT_CHUNKS))
assert validator['ok'] and not validator['chunks_mismatch'] and not validator['citation_issues'],validator
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
audit={'id':spec['id'],'status':'pass','source':{'physical_page':447,'printed_page':391,'image':'evals/runtime_validation/source-p447-7-2-5.png','image_sha256':sha(ROOT/'evals/runtime_validation/source-p447-7-2-5.png'),'visual_review':True,'independent_cells':29,'area_cells':5,'efficiency_cells':24,'recovered_from_extraction_loss':4,'rules':['A=a×E','monthly 20-workday weather condition sets Eweather=1.00','select the worst of weather/current/visibility','ship and auxiliary equipment depreciation/operating costs separately accounted']},'runtime':{'formula_routes':routes,'worst_condition_wins_cases':worst_counts,'all_standard_area_rows_tested':True,'all_depth_and_environment_combinations_tested':True,'citations_include_selected_source_cells':True,'validator':validator,'full_rule_verification':False,'open_scope':['Ship/auxiliary equipment charges are separately accounted and not included in A.']},'hashes':{'spec_sha256':sha(ROOT/'data/drafts/specs/토목/7-2-5.json'),'formula_runtime_sha256':sha(ROOT/'backend/agent/tools/calc/formula.py'),'chunks_sha256':sha(ROOT/'data/processed/chunks.all.jsonl')}}
(ROOT/'evals/runtime_validation/civil-7-2-5-dredging-capacity-audit-2026-10-19.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print(json.dumps({'status':'pass','independent_cells':29,'routes':routes,'winner_cases':worst_counts,'validator':validator['ok']}))
