-- Application rows are read through user JWTs; trusted API writes require ownership checks.
create table public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  display_name text check (char_length(display_name) <= 100),
  created_at timestamptz not null default now()
);

create table public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null check (char_length(title) between 1 and 200),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index conversations_owner_updated_idx
  on public.conversations (user_id, updated_at desc, id);

create table public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  sequence bigint not null check (sequence > 0),
  request_id uuid not null,
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  payload jsonb not null default '{}'::jsonb check (jsonb_typeof(payload) = 'object'),
  created_at timestamptz not null default now(),
  unique (conversation_id, sequence),
  unique (conversation_id, request_id, role)
);

alter table public.profiles enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;
revoke all on public.profiles, public.conversations, public.messages from anon, authenticated;
grant select on public.profiles, public.conversations, public.messages to authenticated;
grant update (display_name) on public.profiles to authenticated;
grant all on public.profiles, public.conversations, public.messages to service_role;

create policy profiles_read_own on public.profiles for select to authenticated
  using (user_id = (select auth.uid()));
create policy profiles_update_own on public.profiles for update to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy conversations_read_own on public.conversations for select to authenticated
  using (user_id = (select auth.uid()));
create policy messages_read_own on public.messages for select to authenticated
  using (exists (
    select 1 from public.conversations c
    where c.id = messages.conversation_id and c.user_id = (select auth.uid())
  ));

-- LangGraph's PostgresSaver will create its internal tables here during API setup.
-- Keep this schema outside the Supabase Data API's exposed schemas.
create schema if not exists agent_state;
revoke all on schema agent_state from public, anon, authenticated;

comment on table public.conversations is 'Member conversations only; id is the persistent agent thread id';
comment on table public.messages is 'Ordered UI transcript; payload is a versioned response, not agent checkpoint state';
