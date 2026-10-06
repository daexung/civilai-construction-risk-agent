-- Only the trusted API writes; operators review in the Supabase dashboard.
create table public.feedback (
  id uuid primary key,
  user_id uuid references auth.users(id) on delete set null,
  subject text not null,
  category text not null check (category in ('bug', 'suggestion', 'other')),
  message text not null check (char_length(message) between 5 and 2000),
  status text not null default 'new' check (status in ('new', 'reviewed', 'resolved')),
  created_at timestamptz not null default now()
);
create index feedback_created_at_idx on public.feedback(created_at desc);
alter table public.feedback enable row level security;
revoke all on public.feedback from public, anon, authenticated;
create table agent_state.daily_feedback_usage (
  usage_day date not null,
  subject text not null,
  used integer not null default 0 check (used >= 0),
  last_at timestamptz,
  primary key (usage_day, subject)
);
revoke all on agent_state.daily_feedback_usage from public, anon, authenticated;
