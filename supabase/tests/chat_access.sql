-- Run against local Supabase only; every fixture is rolled back.
begin;
insert into auth.users (id) values
  ('aaaaaaaa-0000-4000-8000-000000000001'),
  ('bbbbbbbb-0000-4000-8000-000000000001');
insert into public.profiles (user_id, display_name) values
  ('aaaaaaaa-0000-4000-8000-000000000001', 'A'),
  ('bbbbbbbb-0000-4000-8000-000000000001', 'B');
insert into public.conversations (id, user_id, title) values
  ('aaaaaaaa-1111-4000-8000-000000000001', 'aaaaaaaa-0000-4000-8000-000000000001', 'A1'),
  ('aaaaaaaa-1111-4000-8000-000000000002', 'aaaaaaaa-0000-4000-8000-000000000001', 'A2'),
  ('bbbbbbbb-1111-4000-8000-000000000001', 'bbbbbbbb-0000-4000-8000-000000000001', 'B1');
insert into public.messages (conversation_id, sequence, request_id, role, content)
select id, 1, gen_random_uuid(), 'user', title from public.conversations
where id in ('aaaaaaaa-1111-4000-8000-000000000001',
             'aaaaaaaa-1111-4000-8000-000000000002',
             'bbbbbbbb-1111-4000-8000-000000000001');

set local role authenticated;
set local request.jwt.claims = '{"sub":"aaaaaaaa-0000-4000-8000-000000000001","role":"authenticated"}';
do $$ begin
  if (select count(*) from public.conversations) <> 2 then raise exception 'A conversation isolation failed'; end if;
  if (select count(*) from public.messages) <> 2 then raise exception 'A message isolation failed'; end if;
  if (select count(*) from public.profiles) <> 1 then raise exception 'A profile isolation failed'; end if;
  if exists (select 1 from public.messages where conversation_id = 'bbbbbbbb-1111-4000-8000-000000000001') then
    raise exception 'A can read B by conversation id';
  end if;
  if (select count(*) from public.messages where conversation_id = 'aaaaaaaa-1111-4000-8000-000000000001') <> 1 then
    raise exception 'A1 query includes another conversation';
  end if;
  if has_table_privilege(current_user, 'public.messages', 'INSERT') or
     has_table_privilege(current_user, 'public.conversations', 'INSERT') then
    raise exception 'Client can forge persisted transcript';
  end if;
  if has_schema_privilege(current_user, 'agent_state', 'USAGE') then
    raise exception 'Client can access internal checkpoints';
  end if;
end $$;
update public.profiles set display_name = 'A updated' where user_id = 'aaaaaaaa-0000-4000-8000-000000000001';
update public.profiles set display_name = 'forged' where user_id = 'bbbbbbbb-0000-4000-8000-000000000001';

set local request.jwt.claims = '{"sub":"bbbbbbbb-0000-4000-8000-000000000001","role":"authenticated"}';
do $$ begin
  if (select count(*) from public.conversations) <> 1 then raise exception 'B conversation isolation failed'; end if;
  if (select count(*) from public.messages) <> 1 then raise exception 'B message isolation failed'; end if;
  if (select display_name from public.profiles) <> 'B' then raise exception 'A changed B profile'; end if;
end $$;

set local role anon;
set local request.jwt.claims = '{}';
do $$ begin
  if has_table_privilege(current_user, 'public.conversations', 'SELECT') or
     has_table_privilege(current_user, 'public.messages', 'SELECT') or
     has_table_privilege(current_user, 'public.messages', 'INSERT') or
     has_schema_privilege(current_user, 'agent_state', 'USAGE') then
    raise exception 'Guest has persistent chat access';
  end if;
end $$;

reset role;
delete from public.conversations where id = 'aaaaaaaa-1111-4000-8000-000000000001';
do $$ begin
  if exists (select 1 from public.messages where conversation_id = 'aaaaaaaa-1111-4000-8000-000000000001') then
    raise exception 'Conversation deletion did not cascade';
  end if;
  if (select display_name from public.profiles where user_id = 'aaaaaaaa-0000-4000-8000-000000000001') <> 'A updated' then
    raise exception 'Own profile update failed';
  end if;
end $$;
rollback;
select 'PASS: A/B/guest isolation, conversation filtering, write restrictions, checkpoints, profile updates, cascade';
