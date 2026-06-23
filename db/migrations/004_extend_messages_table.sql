-- 004_extend_messages_table.sql
-- messages 테이블 확장 (에이전트 추적)

-- messages 테이블 컬럼 추가
ALTER TABLE messages
ADD COLUMN IF NOT EXISTS agent VARCHAR(50) CHECK (agent IN ('weather', 'labor', 'equipment', 'material', 'synthesize', 'router', NULL));

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(agent);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role);
