-- Private, durable idempotency receipt. No transcripts or plaintext capabilities.
create table if not exists agent_state.guest_imports (
  source_id text primary key,
  secret_hash text not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  conversation_id uuid not null unique references public.conversations(id) on delete cascade,
  created_at timestamptz not null default now()
);
revoke all on agent_state.guest_imports from public, anon, authenticated;
