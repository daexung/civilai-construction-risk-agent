create table agent_state.account_deletion_challenges (
  id uuid primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  original_session_id uuid not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '10 minutes'),
  unique(user_id)
);
-- Durable cleanup queue survives Auth deletion and network/DB interruptions.
create table agent_state.account_deletions (
  user_id uuid primary key,
  conversation_ids uuid[] not null,
  feedback_ids uuid[] not null,
  created_at timestamptz not null default now()
);
revoke all on agent_state.account_deletion_challenges, agent_state.account_deletions from public, anon, authenticated;
