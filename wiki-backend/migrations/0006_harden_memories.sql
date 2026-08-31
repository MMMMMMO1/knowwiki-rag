-- 长期记忆去重、数量治理与重要性范围约束。

ALTER TABLE memories ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64);
UPDATE memories SET content_hash = md5(content) WHERE content_hash IS NULL;
ALTER TABLE memories ALTER COLUMN content_hash SET NOT NULL;

WITH ranked AS (
  SELECT id,
         row_number() OVER (
           PARTITION BY user_id, workspace_id, content_hash
           ORDER BY importance DESC, updated_at DESC, id DESC
         ) AS row_number
  FROM memories
)
DELETE FROM memories WHERE id IN (SELECT id FROM ranked WHERE row_number > 1);

CREATE UNIQUE INDEX IF NOT EXISTS uq_memories_user_workspace_content_hash
  ON memories (user_id, workspace_id, content_hash);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_memories_importance_range'
  ) THEN
    ALTER TABLE memories
      ADD CONSTRAINT ck_memories_importance_range
      CHECK (importance >= 0.0 AND importance <= 1.0);
  END IF;
END $$;
