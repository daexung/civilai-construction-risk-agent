-- Private execution metadata. Existing ratings remain valid without invented history.
create table public.answer_runs (
  answer_id uuid primary key,
  user_id uuid references auth.users(id) on delete cascade,
  conversation_id uuid references public.conversations(id) on delete cascade,
  thread_id text not null,
  code_version text,
  release_id text,
  chunk_set_id text,
  model_name text,
  prompt_version text,
  answer_status text not null,
  execution jsonb not null check (jsonb_typeof(execution) = 'object'),
  created_at timestamptz not null default now()
);
create index answer_runs_created_idx on public.answer_runs(created_at);
create index answer_runs_conversation_idx on public.answer_runs(conversation_id);
alter table public.answer_runs enable row level security;
revoke all on public.answer_runs from public, anon, authenticated;
grant all on public.answer_runs to service_role;

alter table public.answer_feedback
  add column run_id uuid references public.answer_runs(answer_id) on delete set null,
  add column review_status text not null default 'new'
    check (review_status in ('new', 'reviewed', 'resolved')),
  add column error_type text
    check (error_type in ('retrieval', 'calculation', 'explanation', 'other')),
  add column review_note text not null default '' check (char_length(review_note) <= 4000),
  add column expected_evidence jsonb not null default '[]'::jsonb
    check (jsonb_typeof(expected_evidence) = 'array'),
  add column reviewed_at timestamptz;
create index answer_feedback_run_idx on public.answer_feedback(run_id);
comment on table public.answer_runs is
  'Answer execution metadata, no guest question/answer transcript or session credentials. Retained for 90 days; member deletion cascades.';
