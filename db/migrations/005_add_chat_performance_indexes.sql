-- Speed up sidebar and message loading queries.

CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
ON messages(conversation_id, created_at);

CREATE INDEX IF NOT EXISTS idx_conversations_project_updated
ON conversations(project_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_conversations_owner_project_updated
ON conversations(owner_id, project_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_project_members_user_project
ON project_members(user_id, project_id);
