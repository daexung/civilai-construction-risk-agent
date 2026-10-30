import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
ident='2026-정오표1차/토목/7-2-5/수중고르기'
audit_path=root/'evals/runtime_validation/civil-7-2-5-dredging-capacity-audit-2026-10-19.json'
audit=json.loads(audit_path.read_text(encoding='utf8'))
assert audit['status']=='pass' and audit['source']['independent_cells']==29 and audit['runtime']['formula_routes']==320
idx_path=root/'data/drafts/executable.json';idx=json.loads(idx_path.read_text(encoding='utf8'))
candidate=next((x for x in idx['skipped'] if x['id']==ident),{'id':ident,'reason':'no compatible existing calculator in this runner'})
was_executable=ident in idx['executable']
idx['skipped']=[x for x in idx['skipped'] if x['id']!=ident]
idx['executable']=sorted(set([*idx['executable'],ident]))
summary=idx['summary'];summary['executable']=len(idx['executable']);summary['failed']=len(idx['failed'])
summary['skipped_without_compatible_calculator']=len(idx['skipped'])-summary.get('skipped_misfiled',0)
if not was_executable:
 summary['by_calc_type']['formula']['attempted']+=1;summary['by_calc_type']['formula']['executable']+=1
summary['inventory_total']=summary['executable']+summary['failed']+summary['skipped_without_compatible_calculator']+summary['excluded_from_execution']
summary['total']=summary['inventory_total']-summary['excluded_from_execution']
idx_path.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
record={'id':ident,'previous_status':'unsupported','current_status':'executable','previous_reason':candidate['reason'],'root_cause':'The source E table existed in chunks but omitted the cloudy-visibility column and was not attached to the calculation specification; the generic formula runtime lacked a minimum-of-source-values operation and dynamic derived-cell citation propagation.','source_evidence':'Original physical p.447 (printed p.391) visually reviewed. Reconstructed five standard-area cells and all 24 E cells; recovered the four cloudy-visibility cells omitted by extraction.','focused_checks':['320 exact combinations across 5 stone types × 4 depth bands × 2 tide states × 2 currents × 2 visibility conditions × 2 monthly-workday overrides','Worst-condition tie/selection trace with citations to the actual source cell(s); 20-workday override cites p447-x11','Draft validator: format, citations and chunks hash clean','Existing steel-formula focused check passes; formula-module suite recorded separately with unrelated pre-existing setup/dependency errors'],'inventory_replay':'not run','full_rule_verification':False,'remaining_limits':['Ship and auxiliary-equipment depreciation and operating costs remain separately accounted per source and are outside capacity A.'],'audit':str(audit_path.relative_to(root))}
record_path=root/'evals/runtime_validation/executable-7-2-5-source-formula-promotion-2026-10-19.json'
record_path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
rep_path=root/'evals/runtime_validation/execution-id-and-evidence-scope-reconciliation-2026-10-19.json';rep=json.loads(rep_path.read_text(encoding='utf8'))
rep['current_counts']={'executable':len(idx['executable']),'failed':len(idx['failed']),'unsupported':summary['skipped_without_compatible_calculator'],'excluded':summary['excluded_from_execution']}
rep['id_status_delta']['same_id_unsupported_to_executable']+=1;rep['id_status_delta']['net_pass_delta']+=1;rep['id_status_delta']['unchanged_unsupported']-=1
rep['id_status_delta']['unsupported_to_executable_ids'].append({'id':ident,'baseline':'unsupported','baseline_reason':candidate['reason'],'current':'executable','evidence_artifacts':[record_path.name,audit_path.name]})
specroot=root/'data/drafts/specs';entries=[p.relative_to(specroot).as_posix().encode()+b'\0'+hashlib.sha256(p.read_bytes()).hexdigest().encode() for p in sorted(specroot.rglob('*.json'))]
manifest=hashlib.sha256(b'\n'.join(entries)).hexdigest()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
rep['artifacts']['current_spec_manifest_sha256']=manifest
rep['artifacts']['focused_incremental_scope']+='; civil 7-2-5: source E extraction repaired, 29 source cells and 320 formula routes checked, one legacy unsupported ID promoted; no inventory replay.'
cov=rep['source_coverage_scope'];cov['recent_independent_cell_audit']+=' Civil 7-2-5 added 29 independently checked table cells (five standard-area cells and 24 work-efficiency cells; four recovered from source-extraction loss), bringing coverage to 101 sections / 3895 cells.'
cov['relation']='Broad source-derived checks remain 89 sections / 303 cases. Independent source-cell audits are 101 sections / 3895 cells; latest additions and subcounts are recorded in the recent independent-cell audit field. Notes and calculation rules are tracked separately, not included in cell count. Earlier 17/555 is included. Broad-case and cell-audit overlap is unknown; these scopes are not additive.'
rep['common_executor_impact']['focused_current_regression']+='; formula runtime now supports cited minimum of source-derived values and conditional cited literals, used by baseline-unsupported 7-2-5. Verified all 320 routes; existing formula smoke: 8 supported formulas computed, 1 correctly rejected at its source range, and check_steel_formula passed. Test_calculation_modules.py ran 32 tests but had three unrelated errors (two existing fixture/code errors and missing google.genai dependency), 1 skip; no external call made.'
rep['common_executor_impact']['validity']+=' 7-2-5 is the only spec declaring the new minimum/conditional-literal operations; existing baseline-executable formula specs were run with valid representative input sets (8 computed, 1 range-rejected) and check_steel_formula passed.'
rep['current_runtime_hashes'].update({'per_unit_sha256':sha(root/'backend/agent/tools/calc/per_unit.py'),'adjustments_sha256':sha(root/'backend/agent/tools/calc/adjustments.py'),'daily_crew_sha256':sha(root/'backend/agent/tools/calc/daily_crew.py'),'fill_sha256':sha(root/'backend/agent/nodes/fill.py'),'compose_sha256':sha(root/'backend/agent/nodes/compose.py'),'validator_sha256':sha(root/'pipeline/validate_drafts.py'),'executable_index_sha256':sha(idx_path),'chunks_sha256':sha(root/'data/processed/chunks.all.jsonl'),'formula_sha256':sha(root/'backend/agent/tools/calc/formula.py')})
rep_path.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
(root/'evals/runtime_validation/active-table-link-root-causes-2026-10-19.json').write_text(json.dumps({**json.loads((root/'evals/runtime_validation/active-table-link-root-causes-2026-10-19.json').read_text(encoding='utf8')),'active_failure_total':len(idx['failed'])},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
fpath=root/'evals/runtime_validation/current-failures-2026-10-19.json';failures=json.loads(fpath.read_text(encoding='utf8'));fpath.write_text(json.dumps([x for x in failures if x['id']!=ident],ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print(json.dumps({'counts':rep['current_counts'],'promoted':ident,'spec_manifest_sha256':manifest},ensure_ascii=False))
