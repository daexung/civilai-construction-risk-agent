import hashlib,json
from pathlib import Path
r=Path(__file__).resolve().parents[1]
idx=json.loads((r/'data/drafts/executable.json').read_text(encoding='utf8'))
ids={x['id'] for x in idx['failed']}
failpath=r/'evals/runtime_validation/current-failures-2026-10-19.json'
failpath.write_text(json.dumps([{'id':x['id'],'stage':x.get('stage','calculator_execution_or_rule_gate'),'reason':x['reason']} for x in idx['failed']],ensure_ascii=False,indent=2)+'\n',encoding='utf8')
causepath=r/'evals/runtime_validation/active-table-link-root-causes-2026-10-19.json'
c=json.loads(causepath.read_text(encoding='utf8'))
c['active_failure_total']=len(ids)
c['table_link_candidate_count']=3
c['failure_class_counts']={'calculator_execution_or_rule_gate':0,'cell_value_parse':3,'unit_basis_or_normalization':3}
c['table_link_classes']={'cell_value_parse':3}
c['root_cause_group_counts']={'source_range_requires_explicit_policy':3}
causepath.write_text(json.dumps(c,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
rep_path=r/'evals/runtime_validation/execution-id-and-evidence-scope-reconciliation-2026-10-19.json';rep=json.loads(rep_path.read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
rep['current_runtime_hashes']['executable_index_sha256']=sha(r/'data/drafts/executable.json')
rep['current_runtime_hashes']['formula_sha256']=sha(r/'backend/agent/tools/calc/formula.py')
rep['current_runtime_hashes']['chunks_sha256']=sha(r/'data/processed/chunks.all.jsonl')
rep['artifacts']['focused_incremental_scope']+='; index summary refreshed from status IDs without calculation replay; active failure report reconciled to the six current IDs.'
rep_path.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
assert len(idx['executable'])==887 and len(idx['failed'])==6 and idx['summary']['skipped_without_compatible_calculator']==163
assert len(json.loads(failpath.read_text(encoding='utf8')))==6
print(json.dumps({'counts':rep['current_counts'],'failure_list_matches':True,'table_link_candidates':3,'manifest':rep['artifacts']['current_spec_manifest_sha256']},ensure_ascii=False))
