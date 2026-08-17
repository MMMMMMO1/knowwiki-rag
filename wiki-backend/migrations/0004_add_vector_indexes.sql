-- 向量检索性能优化：为 embedding 列增加 HNSW 索引（cosine distance）
-- 幂等迁移：CREATE INDEX IF NOT EXISTS，可重复执行

-- HNSW 索引加速余弦相似度近邻检索；数据量增长后显著降低检索延迟。
-- pgvector 的 vector_cosine_ops 对应查询侧使用的 cosine_distance 排序。
CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding_hnsw
  ON rag_chunks USING hnsw (embedding vector_cosine_ops);

-- 长期记忆表同样用 cosine 距离检索，加同类索引。
CREATE INDEX IF NOT EXISTS ix_memories_embedding_hnsw
  ON memories USING hnsw (embedding vector_cosine_ops);
