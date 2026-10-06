-- Operators review ratings; browsers submit only through the verified API.
create table public.answer_feedback (
  answer_id uuid primary key,
  user_id uuid references auth.users(id) on delete cascade,
  conversation_id uuid references public.conversations(id) on delete cascade,
  thread_id text not null,
  rating text not null check (rating in ('good', 'bad')),
  reason text check (reason in ('amount', 'evidence', 'understanding', 'other')),
  comment text not null default '' check (char_length(comment) <= 1000),
  question text not null,
  answer text not null,
  answer_status text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((rating='good' and reason is null and comment='') or (rating='bad' and reason is not null))
);
create index answer_feedback_created_idx on public.answer_feedback(created_at desc);
alter table public.answer_feedback enable row level security;
revoke all on public.answer_feedback from public, anon, authenticated;
create table agent_state.daily_answer_feedback_usage (
  usage_day date not null,
  subject text not null,
  used integer not null default 0 check (used >= 0),
  primary key (usage_day, subject)
);
revoke all on agent_state.daily_answer_feedback_usage from public, anon, authenticated;
