-- Shared across API workers/restarts. Subjects contain only HMAC identities.
create table if not exists agent_state.daily_chat_usage (
  usage_day date not null,
  subject text not null,
  used integer not null default 0 check (used >= 0),
  primary key (usage_day, subject)
);
revoke all on agent_state.daily_chat_usage from public, anon, authenticated;
