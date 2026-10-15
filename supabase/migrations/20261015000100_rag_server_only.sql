-- Public document knowledge is served through the backend, never through browser DB roles.
do $$ declare row record; begin
  for row in select tablename from pg_tables where schemaname='rag_knowledge' loop
    execute format('alter table rag_knowledge.%I enable row level security',row.tablename);
    execute format('revoke all on rag_knowledge.%I from public,anon,authenticated',row.tablename);
  end loop;
end $$;
revoke all on schema rag_knowledge from public,anon,authenticated;
