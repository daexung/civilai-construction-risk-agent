"""Copy only the pinned, verified public knowledge release in one target transaction.

No member, chat, feedback, usage or trace table is read or modified.
Existing releases are compared and preserved; divergent existing content is refused.
"""
import argparse,hashlib,json,os
from pathlib import Path
import psycopg
from psycopg import sql
from dotenv import load_dotenv
RID='rk-complete-82c206c61e21-37f81b5cfb1b'
CS='cs-37f81b5cfb1b-46f4f035c0fa'
TABLES=['releases','documents','nodes','sections','corrections','toc_entries','source_records','record_cells',
        'search_records','source_relations','edges','edge_candidates','chunk_sets','chunks','chunk_sources',
        'chunk_cells','chunk_links','chunk_exclusions']
def select(c,table):
    cols=c.execute("select a.attname from pg_index i join pg_attribute a on a.attrelid=i.indrelid and a.attnum=any(i.indkey) where i.indrelid=%s::regclass and i.indisprimary order by a.attnum",('rag_knowledge.'+table,)).fetchall()
    where,value=('chunk_set_id',CS) if table.startswith('chunk') else ('release_id',RID)
    return sql.SQL('select * from rag_knowledge.{} where {}={} order by {}').format(sql.Identifier(table),sql.Identifier(where),sql.Literal(value),sql.SQL(',').join(sql.Identifier(x[0]) for x in cols))
def digest(c,table):
    h=hashlib.sha256()
    with c.cursor().copy(sql.SQL('COPY ({}) TO STDOUT').format(select(c,table))) as cp:
        for block in cp:h.update(block)
    return h.hexdigest()
def main():
    a=argparse.ArgumentParser();a.add_argument('--apply',action='store_true');args=a.parse_args()
    root=Path(__file__).resolve().parents[1]
    env=Path(os.environ.get('KNOWLEDGE_ENV_FILE',str(root/'.env')))
    load_dotenv(env,override=False)
    target=os.environ['CHAT_DATABASE_URL']
    report={}
    with psycopg.connect('postgresql://postgres:postgres@127.0.0.1:54322/civilai_rag_verify',connect_timeout=8) as source,psycopg.connect(target,connect_timeout=8) as dest:
        source.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        source.execute("SET TIME ZONE 'UTC'");dest.execute("SET TIME ZONE 'UTC'")
        assert source.execute('select status from rag_knowledge.chunk_sets where chunk_set_id=%s',(CS,)).fetchone()==('complete',)
        if not args.apply:
            for table in TABLES:
                q=select(source,table)
                n=source.execute(sql.SQL('select count(*) from ({}) x').format(q)).fetchone()[0]
                report[table]={'rows':n,'sha256':digest(source,table)}
            print(json.dumps({'mode':'read-only-plan','release_id':RID,'chunk_set_id':CS,'tables':report}),flush=True)
            return
        for name in ['20261011000100_rag_knowledge.sql','20261011000200_rag_search_records.sql','20261012000100_rag_chunks.sql']:
            dest.execute((root/'supabase/migrations'/name).read_text(encoding='utf-8'))
        dest.execute('SET CONSTRAINTS ALL DEFERRED')
        for table in TABLES:
            query=select(source,table)
            count=source.execute(sql.SQL('select count(*) from ({}) x').format(query)).fetchone()[0]
            existing=dest.execute(sql.SQL('select count(*) from ({}) x').format(select(dest,table))).fetchone()[0]
            expected=digest(source,table)
            if existing:
                if count!=existing or digest(dest,table)!=expected:raise ValueError('Existing knowledge differs: '+table)
            else:
                with source.cursor().copy(sql.SQL('COPY ({}) TO STDOUT').format(query)) as read,dest.cursor().copy(sql.SQL('COPY rag_knowledge.{} FROM STDIN').format(sql.Identifier(table))) as write:
                    for block in read:write.write(block)
            if digest(dest,table)!=expected:raise ValueError('Copied knowledge differs: '+table)
            report[table]={'rows':count,'sha256':expected}
            print(json.dumps({'table':table,'rows':count,'content_matches':True}),flush=True)
        dest.execute('SET CONSTRAINTS ALL IMMEDIATE')
        for table in TABLES+['release_channels']:
            dest.execute(sql.SQL('ALTER TABLE rag_knowledge.{} ENABLE ROW LEVEL SECURITY').format(sql.Identifier(table)))
            dest.execute(sql.SQL('REVOKE ALL ON rag_knowledge.{} FROM anon,authenticated,public').format(sql.Identifier(table)))
        assert not dest.execute("select has_schema_privilege('anon','rag_knowledge','USAGE') or has_schema_privilege('authenticated','rag_knowledge','USAGE')").fetchone()[0]
    (root/'tmp').mkdir(exist_ok=True)
    (root/'tmp/knowledge-promotion.json').write_text(json.dumps({'release_id':RID,'chunk_set_id':CS,'tables':report,'status':'committed'},indent=2),encoding='utf-8')
    print('Pinned knowledge committed; browser roles denied; production flag unchanged',flush=True)
if __name__=='__main__':main()
