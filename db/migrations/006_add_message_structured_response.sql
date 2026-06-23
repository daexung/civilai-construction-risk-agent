-- Preserve structured assistant responses for card-style frontend rendering.

ALTER TABLE messages
ADD COLUMN IF NOT EXISTS structured_response JSONB;
