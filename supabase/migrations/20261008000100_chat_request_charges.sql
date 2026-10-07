-- 같은 요청(request_id)은 서버 재시작·다른 인스턴스·동시 요청에서도 한 번만 차감한다.
-- request_key는 HMAC(회원/비회원·소유자·대화·request_id)이라 원래 ID나 사용자 식별자를 저장하지 않는다.
create table if not exists agent_state.chat_request_charges (
  request_key text primary key,
  usage_day date not null,
  charged_at timestamptz not null default now()
);
revoke all on agent_state.chat_request_charges from public, anon, authenticated;
