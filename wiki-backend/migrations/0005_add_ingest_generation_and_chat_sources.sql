-- 同文件入库版本控制、唯一性与聊天来源持久化。

ALTER TABLE rag_documents
  ADD COLUMN IF NOT EXISTS generation INTEGER NOT NULL DEFAULT 1;
ALTER TABLE rag_documents
  ADD COLUMN IF NOT EXISTS processing_generation INTEGER;

-- 历史数据库可能已有重复 file_id；保留最近更新的一条，其余记录及 chunks 级联删除。
WITH ranked AS (
  SELECT id,
         row_number() OVER (
           PARTITION BY file_id
           ORDER BY updated_at DESC NULLS LAST, id DESC
         ) AS row_number
  FROM rag_documents
  WHERE file_id IS NOT NULL
)
DELETE FROM rag_documents
WHERE id IN (SELECT id FROM ranked WHERE row_number > 1);

CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_documents_file_id
  ON rag_documents (file_id)
  WHERE file_id IS NOT NULL;

ALTER TABLE chat_logs
  ADD COLUMN IF NOT EXISTS sources JSONB NOT NULL DEFAULT '[]'::jsonb;
