import hashlib, json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
ident='2026-정오표1차/토목/9-7-3/신규등록측량'
index_path=root/'data/drafts/executable.json'
index=json.loads(index_path.read_text(encoding='utf-8'))
failure=next(x for x in index['failed'] if x['id']==ident)
index['failed']=[x for x in index['failed'] if x['id']!=ident]
index['executable']=sorted([*index['executable'],ident])
index['summary']['executable']=len(index['executable'])
index['summary']['failed']=len(index['failed'])
index['summary']['skipped_without_compatible_calculator']=len(index.get('skipped',[]))-index['summary'].get('skipped_misfiled',0)
index['summary']['inventory_total']=index['summary']['executable']+index['summary']['failed']+index['summary']['skipped_without_compatible_calculator']+index['summary']['excluded_from_execution']
index['summary']['total']=index['summary']['inventory_total']-index['summary']['excluded_from_execution']
index['summary']['by_calc_type']['per_unit']['executable']+=1
index['summary']['by_calc_type']['per_unit']['attempted']+=1
index_path.write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
audit_path=root/'evals/runtime_validation/civil-9-7-3-district-basis-audit-2026-10-19.json'
audit=json.loads(audit_path.read_text(encoding='utf-8'))
record={'id':ident,'previous_status':'failed','current_status':'executable','previous_reason':failure['reason'],'root_cause':'The source extraction omitted two task rows and the specification had no one-district quantity basis. The blocked-policy cites also pointed to a nonexistent p585-x0 chunk.','source_evidence':'Original physical pages 584-585 (printed 528-529) visually checked; 32 numeric table cells independently checked and task rows sum exactly to the source total row.','focused_checks':['9-7-3 district basis route; 94.45/188.65/31.00 person-days per district','32 source cells and independent row totals','noncontinuous area >200000 route; continuous over-area block; >50 parcel block; no-stakeout block','draft validator pass'],'audit':str(audit_path.relative_to(root)),'inventory_replay':'not run','full_rule_verification':False,'remaining_limits':['Continuous-area diminishing coefficient aggregation remains blocked.','More than 50 parcels coefficient remains blocked.','No-stakeout row exclusion remains blocked.']}
record_path=root/'evals/runtime_validation/executable-9-7-3-district-basis-promotion-2026-10-19.json'
record_path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
report_path=root/'evals/runtime_validation/execution-id-and-evidence-scope-reconciliation-2026-10-19.json'
report=json.loads(report_path.read_text(encoding='utf-8'))
report['current_counts']={'executable':len(index['executable']),'failed':len(index['failed']),'unsupported':index['summary']['skipped_without_compatible_calculator'],'excluded':index['summary']['excluded_from_execution']}
report['same_id_fail_to_executable'].append({'id':ident,'baseline':'failed','baseline_reason':failure['reason'],'current':'executable','spec':{'path':'data/drafts/specs/토목/9-7-3.json','title':'신규등록측량','division':'토목','section_no':'9-7-3'},'evidence_artifacts':[record_path.name,audit_path.name]})
report['id_status_delta']['same_id_fail_to_executable']+=1
report['id_status_delta']['net_pass_delta']+=1
report['id_status_delta']['net_fail_delta']-=1
specroot=root/'data/drafts/specs'
entries=[p.relative_to(specroot).as_posix().encode()+b'\0'+hashlib.sha256(p.read_bytes()).hexdigest().encode() for p in sorted(specroot.rglob('*.json'))]
spec_manifest=hashlib.sha256(b'\n'.join(entries)).hexdigest()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
report['artifacts']['current_spec_manifest_sha256']=spec_manifest
report['artifacts']['focused_incremental_scope']+='; civil 9-7-3: two omitted task rows restored, 32 numeric source cells independently checked, one baseline failure promoted; no inventory replay.'
coverage=report['source_coverage_scope']
coverage['recent_independent_cell_audit']+=' Civil 9-7-3 added 32 independently checked table cells (including source row/subtotal/total cells), bringing coverage to 100 sections / 3866 cells.'
coverage['relation']='Broad source-derived checks remain 89 sections / 303 cases. Independent source-cell audits are 100 sections / 3866 cells; latest additions and subcounts are recorded in the recent independent-cell audit field. Notes and calculation rules are tracked separately, not included in cell count. Earlier 17/555 is included. Broad-case and cell-audit overlap is unknown; these scopes are not additive.'
report['common_executor_impact']['focused_current_regression']+='; civil 9-7-3 focused source/calc audit passed (32 cells and three unresolved policy gates; no shared runtime code changed).'
report['current_runtime_hashes'].update({'per_unit_sha256':sha(root/'backend/agent/tools/calc/per_unit.py'),'adjustments_sha256':sha(root/'backend/agent/tools/calc/adjustments.py'),'daily_crew_sha256':sha(root/'backend/agent/tools/calc/daily_crew.py'),'fill_sha256':sha(root/'backend/agent/nodes/fill.py'),'compose_sha256':sha(root/'backend/agent/nodes/compose.py'),'validator_sha256':sha(root/'pipeline/validate_drafts.py'),'executable_index_sha256':sha(index_path),'chunks_sha256':sha(root/'data/processed/chunks.all.jsonl')})
report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
causes_path=root/'evals/runtime_validation/active-table-link-root-causes-2026-10-19.json'
causes=json.loads(causes_path.read_text(encoding='utf-8'));causes['active_failure_total']=len(index['failed']);causes_path.write_text(json.dumps(causes,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
fail_path=root/'evals/runtime_validation/current-failures-2026-10-19.json'
failures=json.loads(fail_path.read_text(encoding='utf-8'));failures=[x for x in failures if x.get('id')!=ident];fail_path.write_text(json.dumps(failures,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'counts':report['current_counts'],'id':ident,'source_cells':audit['source']['task_cell_count'],'spec_manifest_sha256':spec_manifest},ensure_ascii=False))
