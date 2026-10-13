"""4g 고정 기록: 질문·기대값·근거 확인 기록, 코드·모델·프롬프트·스키마·설정·자료 버전 해시, 변경 목록. 실행 전에 한 번 만든다."""
import hashlib, json, os, subprocess, sys, time
from pathlib import Path
sys.dont_write_bytecode = True
HERE = Path(__file__).parent
W = HERE.parents[1]
sys.path.insert(0, str(W / 'src'))
import retrieve as rv  # noqa
import select_verified as sv  # noqa
import select_evidence as se  # noqa

def h(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

out = HERE / 'freeze_04g.json'
assert not out.exists(), '이미 고정됨'
os.environ['AGENT_LLM'] = 'on'
from backend.agent.tools.llm import client as llm  # noqa
rt = rv.Retriever(embed_queries=False)
vs = sv.VerifiedSelector(rt, object())
versions = vs.versions()
ev = W / 'eval'
rec = {
    'frozen_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
    'questions_sha256': h(ev / 'questions_04g_2026-10-12.json'),
    'expected_sha256': h(ev / 'expected_04g_2026-10-12.json'),
    'evidence_check_sha256': h(ev / 'evidence_check_04g_2026-10-12.json'),
    'expectation_builder_sha256': h(HERE / 'prep/build_expectations.py'),
    'pdf_pages_checked_by_eye': sorted(int(p.stem[1:]) for p in (HERE / 'prep/pdf_pages').glob('p*.png')),
    'versions': versions,
    'system_compare_sha256': sv.sha(sv.SYSTEM_COMPARE), 'schema_compare_sha256': sv.sha(sv.SCHEMA_COMPARE),
    'model': {'provider': llm.provider_name(), 'model': llm.model_name()},
    'embedding_config': {'doc_model': 'gemini-embedding-2', 'dim': 3072, 'note': '문서 벡터는 재호출하지 않는다. 새 질문 벡터만 같은 모델로 생성'},
    'src_files_sha256': {p.name: h(p) for p in sorted((W / 'src').glob('*.py'))},
    'run_4g_sha256': h(HERE / 'run_4g.py'),
    'release': vs.store.rid, 'chunk_set': vs.store.cs,
    'git_head': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=W.parents[1], capture_output=True, text=True).stdout.strip(),
    'git_branch': subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=W.parents[1], capture_output=True, text=True).stdout.strip(),
    'git_status_porcelain': subprocess.run(['git', 'status', '--porcelain'], cwd=W.parents[1], capture_output=True, text=True, encoding='utf-8').stdout.splitlines(),
    'caps': {'attempts': 80, 'cost_usd': 2.0},
    'price_assumption': {'source': 'ai.google.dev 공개 단가(입력 $0.30·출력 $2.50 / 100만 토큰). Vertex 서비스 경로의 공식 가격 페이지는 확인하지 못함(4d~4f와 같은 한계)',
                         'query_embedding': '질문당 30토큰·$0.20/100만 토큰으로 보수적 추정'},
    'planned_calls': {'first_run_20': '질문 벡터 20 + 선택 18(번호 질문 2개는 호출 없음) + 목록 판단 4 + 보완 조회·대상 대조 약 6~10 = 약 50~55시도',
                      'repeat_4x2': '선택 4×2 + 보완·대조 약 6~8 + 새 보완 질문 벡터 약 4 = 약 18~20시도', 'total_expected': '약 70~75시도 / 상한 80'},
}
out.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
print(json.dumps({k: rec[k] for k in ('questions_sha256', 'expected_sha256', 'evidence_check_sha256', 'model', 'git_branch')}, ensure_ascii=False))
print('code', versions['select_verified_code_sha256'], 'config', versions['select_verified_config_sha256'])
print('freeze sha', h(out))
rt.close()
