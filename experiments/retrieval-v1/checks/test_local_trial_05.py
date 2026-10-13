"""5단계 로컬 시험 연결 점검(모델·DB 호출 없음). 실행: .venv\\Scripts\\python -B -m pytest experiments/retrieval-v1/checks/test_local_trial_05.py -q

- 옵션 꺼짐 → /api/local-trial/* 404, 기존 앱에는 라우터가 붙지 않음
- (5b단계에서 인용 방식이 원문 위치 선택으로 바뀌어 생성 검증·실패 전환 시험은 test_local_trial_05b.py로 옮겼다)
- 저장된 시험 결과(최신 실행)에서 상태 전달·검토용 원문 누출·버전 혼입 확인
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.pop('LOCAL_TRIAL_RETRIEVAL', None)

from fastapi.testclient import TestClient  # noqa: E402

from backend.api import local_trial as lt  # noqa: E402

def test_option_off_returns_404():
    c = TestClient(lt.app)
    assert c.get('/api/local-trial/health').status_code == 404
    assert c.post('/api/local-trial/ask', json={'message': '질문'}).status_code == 404


def test_main_app_has_no_trial_route_when_off():
    from backend.api.main import app
    assert not any(getattr(r, 'path', '').startswith('/api/local-trial') for r in app.routes)


RESULT = Path(__file__).resolve().parents[1] / 'pilots/step05/trial_results_05_final.json'


@pytest.mark.skipif(not RESULT.exists(), reason='시험 결과 파일 없음')
def test_saved_trial_state_transfer_and_no_review_leak():
    rows = json.loads(RESULT.read_text(encoding='utf-8'))['rows']
    versions = {(r['response']['versions']['release_id'], r['response']['versions']['chunk_set_id']) for r in rows if 'response' in r and r['response'].get('versions')}
    assert len(versions) == 1                        # 버전 혼입 없음
    for r in rows:
        x = r['response']
        if x['status'] == 'not_found':
            assert not (x['sources'] or x['review_material'] or x['related'] or x['list'])
        if x['status'] == 'needs_confirmation':
            assert not x['sources']                  # 확정 출처로 보이는 영역 없음
            assert x['generation']['source'] in ('status_template', 'structural_lookup')
        if x['status'] == 'supported':
            assert x['sources'] and not x['review_material']
        review_ids = {s['id'] for s in x['review_material']}
        assert not (review_ids & {s['id'] for s in x['sources']})   # 검토용이 정상 근거로 섞이지 않음
        assert x.get('applicability', 'unknown') == 'unknown'
