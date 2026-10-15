-- 검색 조각(청크)과 원문 연결. 원문 릴리스(release_id) 위에 청킹 묶음(chunk_set_id)을 둔다.
-- 같은 원문 릴리스에서 청킹 규칙이 바뀌면 다른 chunk_set_id가 된다. 적재 중(loading)인 묶음은 서비스가 읽지 않는다.
-- 다시 실행해도 안전하도록 if not exists를 쓴다.

create table if not exists rag_knowledge.chunk_sets (
  chunk_set_id text primary key,
  release_id text not null references rag_knowledge.releases(release_id),
  status text not null check (status in ('loading', 'complete', 'failed')),
  config jsonb not null,
  input_sha256 text not null,
  code_sha256 jsonb not null,
  counts jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create table if not exists rag_knowledge.chunks (
  chunk_set_id text not null references rag_knowledge.chunk_sets(chunk_set_id) on delete cascade,
  chunk_id text not null,
  release_id text not null,
  ordinal int not null,
  kind text not null check (kind in ('work', 'rule', 'table')),
  section_id text,
  division text,
  title text not null,
  page_first int,
  page_last int,
  part_index int not null default 1,
  part_count int not null default 1,
  context_text text not null,      -- 검색용 문맥(절 제목·소제목·기준·머리글 반복). 원문 인용이 아니다
  body_text text not null,         -- 원문 레코드 글(절 제목 앞머리를 뗀 부분)을 순서대로
  text text not null,              -- 검색·임베딩 입력 = context_text + body_text
  est_tokens int not null,
  token_method text not null,
  status text not null,
  issues jsonb not null default '[]'::jsonb,
  primary key (chunk_set_id, chunk_id),
  unique (chunk_set_id, ordinal),
  foreign key (release_id, section_id) references rag_knowledge.sections(release_id, section_id)
);
create index if not exists chunks_section_idx on rag_knowledge.chunks (chunk_set_id, section_id);

-- 조각에 들어간 검색 입력 행과 역할(body: 원문 인용, context_*: 검색용 문맥, scope_quote: 공종 조각의 적용 범위 인용)
create table if not exists rag_knowledge.chunk_sources (
  chunk_set_id text not null,
  chunk_id text not null,
  ord int not null,
  release_id text not null,
  search_uid text not null,
  role text not null check (role in ('body', 'context_subheading', 'context_basis', 'scope_quote')),
  primary key (chunk_set_id, chunk_id, ord),
  foreign key (chunk_set_id, chunk_id) references rag_knowledge.chunks(chunk_set_id, chunk_id) on delete cascade,
  foreign key (release_id, search_uid) references rag_knowledge.search_records(release_id, search_uid)
);
create index if not exists chunk_sources_uid_idx on rag_knowledge.chunk_sources (chunk_set_id, search_uid);

create table if not exists rag_knowledge.chunk_cells (
  chunk_set_id text not null,
  chunk_id text not null,
  release_id text not null,
  cell_node_id text not null,
  role text not null check (role in ('cell', 'shared_value')),
  primary key (chunk_set_id, chunk_id, cell_node_id, role),
  foreign key (chunk_set_id, chunk_id) references rag_knowledge.chunks(chunk_set_id, chunk_id) on delete cascade,
  foreign key (release_id, cell_node_id) references rag_knowledge.nodes(release_id, node_id)
);
create index if not exists chunk_cells_cell_idx on rag_knowledge.chunk_cells (chunk_set_id, cell_node_id);

-- 조각에서 조회할 대상. 대상 종류마다 다른 열을 쓰고, 하나의 문자열 열에 몰아넣지 않는다.
create table if not exists rag_knowledge.chunk_links (
  chunk_set_id text not null,
  chunk_id text not null,
  release_id text not null,
  link_type text not null,
  target_chunk_id text,
  target_node_id text,
  target_section_id text,
  target_edge_id text,
  confirmed boolean not null,
  status text not null,
  relation_id text,
  link_ord int not null,
  primary key (chunk_set_id, chunk_id, link_ord),
  check (num_nonnulls(target_chunk_id, target_node_id, target_section_id, target_edge_id) = 1),
  foreign key (chunk_set_id, chunk_id) references rag_knowledge.chunks(chunk_set_id, chunk_id) on delete cascade,
  foreign key (chunk_set_id, target_chunk_id) references rag_knowledge.chunks(chunk_set_id, chunk_id) on delete cascade
    deferrable initially deferred,
  foreign key (release_id, target_node_id) references rag_knowledge.nodes(release_id, node_id),
  foreign key (release_id, target_section_id) references rag_knowledge.sections(release_id, section_id),
  foreign key (release_id, target_edge_id) references rag_knowledge.edges(release_id, edge_id),
  foreign key (release_id, relation_id) references rag_knowledge.source_relations(release_id, relation_id)
);
create unique index if not exists chunk_links_unique_idx on rag_knowledge.chunk_links
  (chunk_set_id, chunk_id, link_type, coalesce(target_chunk_id, ''), coalesce(target_node_id, ''),
   coalesce(target_section_id, ''), coalesce(target_edge_id, ''));
create index if not exists chunk_links_target_node_idx on rag_knowledge.chunk_links (chunk_set_id, target_node_id);
create index if not exists chunk_links_target_edge_idx on rag_knowledge.chunk_links (chunk_set_id, target_edge_id);
create index if not exists chunk_links_target_chunk_idx on rag_knowledge.chunk_links (chunk_set_id, target_chunk_id);

-- 검색 조각에 넣지 않은 입력과 사유(목차·표지 등). 원문은 search_records에 그대로 있다.
create table if not exists rag_knowledge.chunk_exclusions (
  chunk_set_id text not null references rag_knowledge.chunk_sets(chunk_set_id) on delete cascade,
  release_id text not null,
  search_uid text not null,
  reason text not null,
  primary key (chunk_set_id, search_uid),
  foreign key (release_id, search_uid) references rag_knowledge.search_records(release_id, search_uid)
);

grant select, insert, update, delete on rag_knowledge.chunk_sets, rag_knowledge.chunks, rag_knowledge.chunk_sources,
  rag_knowledge.chunk_cells, rag_knowledge.chunk_links, rag_knowledge.chunk_exclusions to service_role;
