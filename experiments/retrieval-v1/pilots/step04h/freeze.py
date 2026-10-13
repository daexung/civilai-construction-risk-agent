"""4h 고정 기록: 코드·설정·프롬프트·스키마·자료 버전 해시와 개발 기대 파일 해시를 최종 확인 전에 한 번 남긴다."""
import hashlib, json, os, sys, time
from pathlib import Path
sys.dont_write_bytecode = True
HERE = Path(__file__).parent
W = HERE.parents[1]
sys.path.insert(0, str(W / 'src'))
import retrieve as rv  # noqa
import select_verified as sv  # noqa
def h(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
out = HERE / 'freeze_04h.json'
assert not out.exists()
os.environ['AGENT_LLM'] = 'on'
from backend.agent.tools.llm import client as llm  # noqa
rt = rv.Retriever(embed_queries=False)
vs = sv.VerifiedSelector(rt, object())
prev = json.loads((W / 'pilots/step04g/freeze_04g.json').read_text(encoding='utf-8'))
rec = {'frozen_at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'versions': vs.versions(),
       'system_compare_sha256': sv.sha(sv.SYSTEM_COMPARE), 'schema_compare_sha256': sv.sha(sv.SCHEMA_COMPARE),
       'model': {'provider': llm.provider_name(), 'model': llm.model_name()},
       'dev_cases_4h_sha256': h(HERE / 'dev_cases_4h.json'),
       'questions_04g_sha256': h(W / 'eval/questions_04g_2026-10-12.json'), 'expected_04g_sha256': h(W / 'eval/expected_04g_2026-10-12.json'),
       'previous_4g_code_sha256': prev['versions']['select_verified_code_sha256'],
       'prompt_schema_unchanged_vs_4g': {k: prev['versions'][k] == vs.versions()[k] for k in ('system_select_sha256', 'schema_select_sha256', 'system_list_sha256', 'schema_list_sha256')},
       'compare_prompt_unchanged_vs_4g': {'system': prev['system_compare_sha256'] == sv.sha(sv.SYSTEM_COMPARE), 'schema': prev['schema_compare_sha256'] == sv.sha(sv.SCHEMA_COMPARE)},
       'config': {'target_compare': sv.CONFIG['target_compare'], 'list_scope': sv.CONFIG['list_scope']},
       'caps': {'attempts': 30, 'cost_usd': 1.0}}
out.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
print(json.dumps({k: rec[k] for k in ('prompt_schema_unchanged_vs_4g', 'compare_prompt_unchanged_vs_4g', 'config')}, ensure_ascii=False))
print('code', rec['versions']['select_verified_code_sha256'])
rt.close()
