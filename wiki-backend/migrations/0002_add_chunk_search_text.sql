-- 混合检索：为 rag_chunks 增加关键词检索能力
-- 幂等迁移：ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS，可重复执行

-- search_text 存应用层 jieba 分词后的空格分隔文本，
-- 原始中文默认分词器切不动，所以分词放在 Python 侧完成。
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS search_text TEXT;

-- GIN 索引建在 to_tsvector('simple', search_text) 表达式上，加速关键词检索。
-- 已有数据 search_text 为 NULL 时，索引会自动跳过 NULL，不影响。
CREATE INDEX IF NOT EXISTS ix_rag_chunks_search_text_tsv
  ON rag_chunks USING gin (to_tsvector('simple', search_text));

-- 已有数据平滑升级：
--   search_text 为 NULL 的旧 chunk 不会参与关键词检索（属于优雅降级），
--   需要回填时重新跑一次「全量补齐」（/admin/knowledge/rebuild）即可，
--   它会重新执行入库流水线并生成 search_text。
