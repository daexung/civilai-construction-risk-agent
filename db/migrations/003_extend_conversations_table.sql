-- 003_extend_conversations_table.sql
-- conversations 테이블 확장 (소유자, 공개 범위, 업데이트 시간)

-- conversations 테이블 컬럼 추가
ALTER TABLE conversations
ADD COLUMN IF NOT EXISTS owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS visibility VARCHAR(50) NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'project_shared')),
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_conversations_owner_id ON conversations(owner_id);
CREATE INDEX IF NOT EXISTS idx_conversations_visibility ON conversations(visibility);
CREATE INDEX IF NOT EXISTS idx_conversations_updated_at ON conversations(updated_at);
