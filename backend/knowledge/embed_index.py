"""Read prebuilt embeddings. Document embedding generation is not a serving operation."""
import base64,hashlib,json,os
from pathlib import Path
import numpy as np
import psycopg
from . import db,evidence as ev
from backend.shared import embedding as emb
CS=ev.DEFAULT_CS
INPUT_FORMAT='doc-title-none-v1'
QUERY_FORMAT='query-task-search-result-v1'
CFG=emb.EmbeddingSettings('studio','gemini-embedding-2',3072)
BASE=Path(os.environ.get('KNOWLEDGE_ASSET_DIR',str(Path(__file__).resolve().parents[2]/'data/knowledge')))
CACHE=BASE/'unused-cache'
QUERY_CACHE=BASE/'unused-query-cache'
def sha(s):return hashlib.sha256(s.encode('utf-8')).hexdigest()
def pack_document(text):
    chunk={'section':'none','text':text}
    return emb.document_input(chunk,CFG),emb.document_fingerprint(chunk,CFG)
def enc(vec):return base64.b64encode(np.asarray(vec,dtype='<f4').tobytes()).decode()
def dec(s):return np.frombuffer(base64.b64decode(s),dtype='<f4')
def load_cache(path):return {}
def append_rows(path,rows):pass # Query cache is process-memory only; never persist user query text.
def make_client():return emb.client(CFG),[]
def check_vectors(vecs,n):
    a=np.asarray(vecs)
    if a.shape!=(n,CFG.dim) or not np.isfinite(a).all() or np.any(np.linalg.norm(a,axis=1)==0):
        raise ValueError('Invalid query vectors')
def load_inputs(conn=None):
    own = conn is None
    conn = conn or psycopg.connect(db.dsn())
    if own:
        conn.read_only = True
    rd = ev.Reader(conn, CS)          # 버전·완료 상태 확인(다르면 거부)
    rows = conn.execute("""select chunk_id, kind, section_id, division, status, ordinal, est_tokens, issues, text
                           from rag_knowledge.chunks where chunk_set_id=%s order by ordinal""", (CS,)).fetchall()
    out = []
    for cid, kind, sec, div, status, ordinal, est_tok, issues, text in rows:
        s, h = pack_document(text)
        out.append({'chunk_id': cid, 'kind': kind, 'section_id': sec, 'division': div, 'status': status, 'ordinal': ordinal,
                    'est_tokens': est_tok, 'issues': issues if isinstance(issues, list) else json.loads(issues), 'text': text,
                    'input': s, 'input_sha256': h})
    if own:
        conn.close()
    return out, rd.rid

