-- 원문 대조 교정 자료와, 다음 청킹이 읽을 검색 입력(search_records).
-- source_records는 파싱 원본 레코드 그대로 두고, 교정으로 절 제목이 바뀐 글과 원문에서 보완한 글은 여기에만 둔다.
-- 다시 실행해도 안전하도록 if not exists를 쓴다.

create table if not exists rag_knowledge.corrections (
  release_id text not null references rag_knowledge.releases(release_id) on delete cascade,
  correction_id text not null,
  kind text not null,
  data jsonb not null,
  primary key (release_id, correction_id)
);

create table if not exists rag_knowledge.search_records (
  release_id text not null,
  search_uid text not null,
  search_idx int not null,
  origin text not null check (origin in ('original', 'section_corrected', 'added_from_pdf')),
  record_uid text,
  correction_id text,
  kind text not null,
  page int not null,
  source_node_id text not null,
  section_id text,
  section_text text not null,
  text text not null,
  previous_section_text text,
  primary key (release_id, search_uid),
  unique (release_id, search_idx),
  check ((origin = 'added_from_pdf') = (record_uid is null)),
  check ((origin = 'original') = (correction_id is null)),
  foreign key (release_id, record_uid) references rag_knowledge.source_records(release_id, record_uid) on delete cascade,
  foreign key (release_id, correction_id) references rag_knowledge.corrections(release_id, correction_id) on delete cascade,
  foreign key (release_id, source_node_id) references rag_knowledge.nodes(release_id, node_id) on delete cascade,
  foreign key (release_id, section_id) references rag_knowledge.sections(release_id, section_id) on delete cascade
);
create index if not exists search_records_record_idx on rag_knowledge.search_records (release_id, record_uid);
create index if not exists search_records_node_idx on rag_knowledge.search_records (release_id, source_node_id);
create index if not exists search_records_section_idx on rag_knowledge.search_records (release_id, section_id);

grant select, insert, update, delete on rag_knowledge.corrections, rag_knowledge.search_records to service_role;
