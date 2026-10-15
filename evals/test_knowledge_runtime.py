"""Production routing and state authority checks; no model or remote database calls."""
from unittest.mock import patch,MagicMock
from backend.knowledge import runtime
from backend.agent.estimate import tools,dialogue
from backend.agent.nodes import retrieve,answer
from backend.api import dialogue_service
import pytest

def sample(status='needs_confirmation'):
    return {'answer':'확인할 원문이에요.','answer_status_label':'확인 필요','answer_status':status,
            'status':status,'sources':[],'related':[],'review_material':[],
            'versions':{'chunk_set_id':'fixed','release_id':'fixed'},'confirmations':[],'alternatives':[]}

def test_default_off(monkeypatch):
    monkeypatch.delenv('KNOWLEDGE_RETRIEVAL',raising=False)
    assert not runtime.enabled()

def test_chat_uses_verified_result(monkeypatch):
    monkeypatch.setenv('KNOWLEDGE_RETRIEVAL','v1');r=sample()
    with patch.object(runtime,'ask',return_value=r) as ask:
        result=tools.search_standard('질문')
    ask.assert_called_once_with('질문');assert result['data']['knowledge']==r

def test_injected_hits_keep_existing_test_path(monkeypatch):
    monkeypatch.setenv('KNOWLEDGE_RETRIEVAL','v1')
    with patch.object(runtime,'ask') as ask,patch.object(tools,'build_context',return_value=[]):
        tools.search_standard('질문',hits=[])
    ask.assert_not_called()

def test_estimate_search_uses_new_chunks(monkeypatch):
    monkeypatch.setenv('KNOWLEDGE_RETRIEVAL','v1')
    expected={'hits':[{'chunk_id':'new'}],'search_info':{'method':'knowledge-v1-hybrid'}}
    with patch.object(runtime,'search',return_value=expected):
        assert retrieve._retrieve_impl({'query':'공종'})==expected

def test_legacy_graph_qa_uses_new_policy(monkeypatch):
    monkeypatch.setenv('KNOWLEDGE_RETRIEVAL','v1')
    with patch.object(runtime,'ask',return_value=sample()):
        r=answer.answer({'query':'질문'})
    assert r['knowledge']['status']=='needs_confirmation' and r['qa'] is None

def test_dialogue_does_not_rewrite_or_upgrade():
    r=sample()
    log=[{'tool':'search_standard','result':{'status':'ok','data':{'knowledge':r}}}]
    generate=MagicMock()
    out=dialogue._reply({},log,[],'질문',None,generate,True)
    assert out['knowledge']==r and out['text']==r['answer']
    generate.assert_not_called()

def test_public_response_removes_trial_and_raw_model_data():
    r=sample();r.update(diagnostic=[{'secret':'raw'}],generation={'raw_text':'model'},request_id='internal')
    out=runtime.public_result(r)
    assert 'diagnostic' not in out and 'generation' not in out and 'request_id' not in out
    assert out['versions']['runtime']=='knowledge-v1'

def test_source_uses_existing_page_route():
    r=sample();r['review_material']=[{'pdf_page':185}]
    out=runtime.public_result(r)
    assert out['review_material'][0]['image_url']=='/api/source/p185.png'
    assert not out['sources']

def test_request_call_budget_never_calls_model_after_limit():
    caller=runtime.Caller();caller.attempts=6
    with patch.object(runtime.llm,'generate') as call:
        assert not caller.call('select','s','p',{})['ok']
    call.assert_not_called()

def test_model_failure_is_explicit():
    with patch.object(runtime.llm,'generate',side_effect=runtime.llm.LLMUnavailable('failure')):
        out=runtime.Caller().call('select','s','p',{})
    assert not out['ok'] and out['error']=='model_unavailable'

def test_dialogue_restore_retains_knowledge():
    r=sample()
    with patch('backend.api.main._build_response',return_value={'questions':[]}),patch.object(dialogue_service,'legacy_state',return_value={}):
        result=dialogue_service.response('test',{'turn':{'knowledge':r}})
    assert result['knowledge']==r
