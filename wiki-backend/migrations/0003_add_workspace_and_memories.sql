-- 工作区隔离 + 长期记忆
-- 幂等迁移：ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS，可重复执行

-- workspace_id 在写入阶段打上命名空间标签，检索时按它过滤，实现多知识域隔离。
-- 已有数据全部回填 'default'，检索行为与升级前一致（零数据丢失）。
ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS workspace_id VARCHAR(100) NOT NULL DEFAULT 'default';
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS workspace_id VARCHAR(100) NOT NULL DEFAULT 'default';

CREATE INDEX IF NOT EXISTS ix_rag_documents_workspace_id ON rag_documents (workspace_id);
CREATE INDEX IF NOT EXISTS ix_rag_chunks_workspace_id ON rag_chunks (workspace_id);

-- memories 表：长期记忆（跨会话向量化存储）。
-- 新库由 Base.metadata.create_all 自动建表；此处 IF NOT EXISTS 兜底已有库。
-- 注意：embedding 维度固定 1024，与 text-embedding-v3 绑定。
CREATE TABLE IF NOT EXISTS memories (
    id                SERIAL PRIMARY KEY,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id      VARCHAR(100) NOT NULL DEFAULT 'default',
    content           TEXT NOT NULL,
    embedding         vector(1024),
    importance        DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    source_session_id VARCHAR(100),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_memories_user_workspace ON memories (user_id, workspace_id);
