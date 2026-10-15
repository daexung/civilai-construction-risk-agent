"""Production adapter for frozen retrieval-v1 and verified answer policy 4h/5b.

Knowledge reads are read-only; no migration, document embedding, trial ledger or saved
model responses run here. Existing chat ownership, usage and trace wrappers remain in charge.
"""
from __future__ import annotations
import json,os,threading,time,uuid
from functools import cache
from pathlib import Path
import psycopg
from backend.shared import answer_trace
from backend.agent.tools.llm import client as llm
from . import retrieve as rv,select_verified as sv,embed_index as ei,db
from .response import ResponseBuilder

def enabled():
    return os.environ.get('KNOWLEDGE_RETRIEVAL','legacy')=='v1'

class Caller:
    """Request-scoped model budget. Never monkeypatch the shared model client."""
    def __init__(self):
        self.usage=[]
        self.attempts=0
    def call(self,role,system,prompt,schema,qid=None,run_id=None):
        if self.attempts>=6:
            return {'ok':False,'error':'request_call_limit','attempts':0,'role':role,'cached':False}
        self.attempts+=1
        started=time.perf_counter()
        with answer_trace.step('knowledge_'+role,'model',{'policy':'4h'}) as trace:
            try:
                res=llm.generate(prompt,system,response_schema=schema,timeout_ms=20_000,max_attempts=1)
                if trace is not None: trace['output_summary']={'ok':True}
                return {'ok':True,'raw_text':res.text,'role':role,'attempts':getattr(res,'attempts',1),'cached':False,'usage':[],
                        'cost_usd':0.0,'latency_sec':round(time.perf_counter()-started,3)}
            except llm.LLMUnavailable:
                return {'ok':False,'error':'model_unavailable','role':role,'attempts':1,'cached':False,'usage':[]}

class Engine(ResponseBuilder):
    def __init__(self):
        self.lock=threading.RLock()
        conn=psycopg.connect(db.dsn(),connect_timeout=8,autocommit=True,options='-c statement_timeout=20000')
        conn.read_only=True
        try:
            self.rt=rv.Retriever(conn=conn)
            self.caller=Caller()
            self.vs=sv.VerifiedSelector(self.rt,self.caller)
        except Exception:
            conn.close()
            raise
        self.sv,self.llm=sv,llm
        self.versions=self.vs.versions()
        page_map=Path(__file__).resolve().parents[2]/'data/processed/page_map.json'
        self.pages=json.loads(page_map.read_text(encoding='utf-8'))['pages']
        self.qa_model=json.loads(llm.CONFIG_PATH.read_text(encoding='utf-8')).get('qa_model',llm.model_name())
        self.prompt=(Path(__file__).resolve().parents[1]/'api/local_trial_qa.md').read_text(encoding='utf-8')
    def totals(self):return (0,0.0)
    def ledger_add(self,*a,**k):pass
    def ask(self,question):
        with self.lock:
            self.caller=Caller()
            self.vs.caller=self.caller
            rid=uuid.uuid4().hex
            with answer_trace.step('knowledge_select','tool',{'chunk_set_id':ei.CS,'policy':'4h'}):
                selected=self.vs.run(question,qid=rid,run_id='production',fallback=False)
            result=self.build_response(question,rid,selected)
            return public_result(result)
    def hits(self,question,k=10):
        with self.lock:
            found=self.rt.search(question,'hybrid')
            out=[]
            for h in found['fused']:
                chunk=self.rt.by_id[h['chunk_id']]
                sec=self.vs.sel.sec.get(chunk['section_id'],{})
                out.append({'rank':len(out)+1,'score':h['score'],'chunk_id':h['chunk_id'],'kind':chunk['kind'],
                            'division':(sec.get('division') or '').removesuffix('부문'),'section_no':sec.get('number'),
                            'section':f"{sec.get('number','')} {sec.get('title','')}",'page':sec.get('first_page'),
                            'table_id':None,'structure':{},'text':chunk['text'][:200]})
                if len(out)>=k:break
            return {'hits':out,'search_info':{'method':'knowledge-v1-hybrid','queries':[question],'api_calls':self.rt.api_calls,
                       'warnings':[],'release_id':self.rt.reader.rid,'chunk_set_id':ei.CS}}

def public_result(result):
    keep=('status','status_label','search_status','answer_status','answer_status_label','answer_status_reason',
          'answer','reasons','confirmations','sources','related','review_material','alternatives','citations','value_claims',
          'list','applicability','versions')
    out={key:result.get(key) for key in keep}
    # Display source pages via existing authenticated proxy. No experiment route is exposed.
    for key in ('sources','related','review_material'):
        for source in out.get(key) or []:
            page=source.get('pdf_page')
            source['image_url']=f'/api/source/p{page}.png' if page else None
    out['versions']['runtime']='knowledge-v1'
    return out

_ENGINE=None
_LOCK=threading.Lock()
def engine():
    global _ENGINE
    if _ENGINE is None:
        with _LOCK:
            if _ENGINE is None:_ENGINE=Engine()
    return _ENGINE

def ask(question):return engine().ask(question)
def search(question):return engine().hits(question)
