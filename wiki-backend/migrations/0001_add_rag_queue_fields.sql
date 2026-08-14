-- RAG 消息队列改造：为 rag_documents 增加队列状态字段
-- 幂等迁移：ADD COLUMN IF NOT EXISTS，可重复执行
-- 已有数据库升级时执行本文件即可，无需清空 volume

ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS queued_at TIMESTAMPTZ;
ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMPTZ;
ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS failed_at TIMESTAMPTZ;

-- 可选：为 status / retry_count 建立索引，加速管理后台状态统计
CREATE INDEX IF NOT EXISTS ix_rag_documents_status ON rag_documents (status);
CREATE INDEX IF NOT EXISTS ix_rag_documents_retry_count ON rag_documents (retry_count);
