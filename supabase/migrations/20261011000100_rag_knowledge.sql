-- 품셈 원문·절·참조 저장소(1단계). 회원·대화 테이블(public, agent_state)과 분리한 전용 스키마.
-- Supabase Data API 노출 스키마(public, graphql_public)에 넣지 않는다. 브라우저 역할(anon, authenticated)은 접근하지 않는다.
-- 모든 자료는 release_id로 묶는다. 같은 release_id를 다시 적재하면 적재 코드가 한 트랜잭션에서 지우고 다시 넣는다.
-- 청크·임베딩 테이블은 다음 단계 마이그레이션에서 추가한다.
-- 다시 실행해도 안전하도록 if not exists를 쓴다.

create schema if not exists rag_knowledge;
revoke all on schema rag_knowledge from public, anon, authenticated;

create table if not exists rag_knowledge.releases (
  release_id text primary key,
  generation_id text not null,
  status text not null check (status in ('loading', 'complete', 'failed')),
  input_manifest jsonb not null,
  code_sha256 jsonb not null,
  row_counts jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

-- 서비스가 읽을 릴리스. 적재는 활성 릴리스를 바꾸지 않는다(별도 명령으로만 전환).
create table if not exists rag_knowledge.release_channels (
  channel text primary key,
  release_id text not null references rag_knowledge.releases(release_id),
  updated_at timestamptz not null default now()
);

create table if not exists rag_knowledge.documents (
  release_id text not null references rag_knowledge.releases(release_id) on delete cascade,
  document_id text not null,
  title text not null,
  year int not null,
  version_label text not null,
  pdf_path text not null,
  pdf_sha256 text not null,
  raw_sha256 text not null,
  generation_id text not null,
  pages int not null,
  primary key (release_id, document_id)
);

-- 원문 노드: 제목·본문·기준·표·칸·행 묶음·제외 글. 원래 식별자를 그대로 node_id로 쓴다.
create table if not exists rag_knowledge.nodes (
  release_id text not null,
  node_id text not null,
  document_id text not null,
  kind text not null check (kind in ('heading', 'note', 'basis', 'table', 'cell', 'table_group', 'skipped_text')),
  page int,
  doc_order int,
  odl_id text,
  bbox jsonb,
  text text,
  parent_node_id text,
  division text,
  region text not null check (region in ('front', 'cover', 'body')),
  structure jsonb not null default '{}'::jsonb,
  primary key (release_id, node_id),
  foreign key (release_id, document_id) references rag_knowledge.documents(release_id, document_id) on delete cascade,
  foreign key (release_id, parent_node_id) references rag_knowledge.nodes(release_id, node_id)
    on delete cascade deferrable initially deferred
);
create index if not exists nodes_page_idx on rag_knowledge.nodes (release_id, page, doc_order);
create index if not exists nodes_parent_idx on rag_knowledge.nodes (release_id, parent_node_id);

-- 실제 본문 절 목록. 목차 줄은 toc_entries에 따로 둔다.
create table if not exists rag_knowledge.sections (
  release_id text not null,
  section_id text not null,
  document_id text not null,
  division text not null,
  level text not null check (level in ('chapter', 'group', 'section')),
  number text not null,
  title text not null,
  title_raw text not null,
  heading_node_id text not null,
  parent_section_id text,
  start_order int not null,
  end_order int not null,
  first_page int not null,
  last_page int not null,
  status text not null,
  evidence jsonb not null default '{}'::jsonb,
  primary key (release_id, section_id),
  unique (release_id, document_id, division, level, number),
  foreign key (release_id, document_id) references rag_knowledge.documents(release_id, document_id) on delete cascade,
  foreign key (release_id, heading_node_id) references rag_knowledge.nodes(release_id, node_id) on delete cascade,
  foreign key (release_id, parent_section_id) references rag_knowledge.sections(release_id, section_id)
    on delete cascade deferrable initially deferred
);
create index if not exists sections_number_idx on rag_knowledge.sections (release_id, number, division);

create table if not exists rag_knowledge.toc_entries (
  release_id text not null,
  toc_id text not null,
  node_id text not null,
  division text,
  number text,
  title text not null,
  printed_page int,
  matched_section_id text,
  match_status text not null,
  primary key (release_id, toc_id),
  foreign key (release_id, node_id) references rag_knowledge.nodes(release_id, node_id) on delete cascade,
  foreign key (release_id, matched_section_id) references rag_knowledge.sections(release_id, section_id) on delete cascade
);

-- 원문 레코드 23,481개. record 원래 JSON과 연결 정보(link)를 그대로 보관한다.
create table if not exists rag_knowledge.source_records (
  release_id text not null,
  record_uid text not null,
  record_idx int not null,
  kind text not null,
  page int not null,
  text text not null,
  source_node_id text not null,
  section_id text,
  record jsonb not null,
  link jsonb not null,
  primary key (release_id, record_uid),
  unique (release_id, record_idx),
  foreign key (release_id, source_node_id) references rag_knowledge.nodes(release_id, node_id) on delete cascade,
  foreign key (release_id, section_id) references rag_knowledge.sections(release_id, section_id) on delete cascade
);
create index if not exists source_records_node_idx on rag_knowledge.source_records (release_id, source_node_id);

-- 레코드가 가리키는 원문 칸(역할: 값·이름·머리글 등)
create table if not exists rag_knowledge.record_cells (
  release_id text not null,
  record_uid text not null,
  cell_node_id text not null,
  primary key (release_id, record_uid, cell_node_id),
  foreign key (release_id, record_uid) references rag_knowledge.source_records(release_id, record_uid) on delete cascade,
  foreign key (release_id, cell_node_id) references rag_knowledge.nodes(release_id, node_id) on delete cascade
);
create index if not exists record_cells_cell_idx on rag_knowledge.record_cells (release_id, cell_node_id);

-- 기존 관계 11,823건 원본. 끝점이 노드가 아니면 원시 값과 정규화 상태만 남긴다(노드를 만들지 않는다).
create table if not exists rag_knowledge.source_relations (
  release_id text not null,
  relation_id text not null,
  type text not null,
  from_raw text,
  to_raw text,
  from_node_id text,
  to_node_id text,
  from_norm text not null,
  to_norm text not null,
  confirmed boolean not null,
  status text not null,
  raw jsonb not null,
  primary key (release_id, relation_id),
  foreign key (release_id, from_node_id) references rag_knowledge.nodes(release_id, node_id) on delete cascade,
  foreign key (release_id, to_node_id) references rag_knowledge.nodes(release_id, node_id) on delete cascade
);
create index if not exists source_relations_from_idx on rag_knowledge.source_relations (release_id, from_node_id);
create index if not exists source_relations_to_idx on rag_knowledge.source_relations (release_id, to_node_id);

-- 정규화한 참조 연결. 대상 확인(target_status)과 기존 파싱 상태(source_confirmed)는 다른 필드다.
-- 적용 여부(applies/does_not_apply)는 질문별 조회 기록에 둔다. 여기에 저장하지 않는다.
create table if not exists rag_knowledge.edges (
  release_id text not null,
  edge_id text not null,
  origin text not null check (origin in ('existing_reference', 'scan_candidate')),
  relation_id text,
  from_node_id text not null,
  expression text not null,
  sentence text not null,
  condition_text text,
  target_division text,
  target_number text,
  target_subitem text,
  target_status text not null check (target_status in ('resolved', 'partial', 'ambiguous', 'missing', 'external')),
  reason text not null,
  method text not null,
  source_confirmed boolean,
  source_status text,
  evidence jsonb not null default '{}'::jsonb,
  primary key (release_id, edge_id),
  foreign key (release_id, relation_id) references rag_knowledge.source_relations(release_id, relation_id) on delete cascade,
  foreign key (release_id, from_node_id) references rag_knowledge.nodes(release_id, node_id) on delete cascade
);
create index if not exists edges_from_idx on rag_knowledge.edges (release_id, from_node_id);

-- 확정 대상(role='target')과 미확정 후보(role='candidate')
create table if not exists rag_knowledge.edge_candidates (
  release_id text not null,
  edge_id text not null,
  rank int not null,
  role text not null check (role in ('target', 'candidate')),
  section_id text not null,
  subitem_node_id text,
  reason text not null,
  primary key (release_id, edge_id, rank),
  foreign key (release_id, edge_id) references rag_knowledge.edges(release_id, edge_id) on delete cascade,
  foreign key (release_id, section_id) references rag_knowledge.sections(release_id, section_id) on delete cascade,
  foreign key (release_id, subitem_node_id) references rag_knowledge.nodes(release_id, node_id) on delete cascade
);
create index if not exists edge_candidates_section_idx on rag_knowledge.edge_candidates (release_id, section_id);

-- 외래 키 쪽 색인(재적재 때 삭제·연쇄 삭제가 전체 테이블을 훑지 않게)
create index if not exists sections_heading_idx on rag_knowledge.sections (release_id, heading_node_id);
create index if not exists sections_parent_idx on rag_knowledge.sections (release_id, parent_section_id);
create index if not exists toc_entries_node_idx on rag_knowledge.toc_entries (release_id, node_id);
create index if not exists toc_entries_section_idx on rag_knowledge.toc_entries (release_id, matched_section_id);
create index if not exists source_records_section_idx on rag_knowledge.source_records (release_id, section_id);
create index if not exists edges_relation_idx on rag_knowledge.edges (release_id, relation_id);
create index if not exists edge_candidates_subitem_idx on rag_knowledge.edge_candidates (release_id, subitem_node_id);

-- 권한: 서버 전용 역할만 읽고 쓴다.
grant usage on schema rag_knowledge to service_role;
grant select, insert, update, delete on all tables in schema rag_knowledge to service_role;
