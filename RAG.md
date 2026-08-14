# RAG 自研模块设计文档

> **迁移状态**：自研 RAG 已于 2026-08 全面替代 AnythingLLM。AnythingLLM 容器、代码、API 均已被 `wiki-backend/rag/` 模块替代。
> 本文档保留设计决策和参考对比，供后续维护参考。
>
> **分支说明**：`rag-rewrite` 是自研 RAG 的独立版本分支。`wiki-backend/anythingllm/` 仅为历史目录名（内含当前 RAG 版 compose 编排与数据目录），不再运行 AnythingLLM。

项目：wiki-main（Wiki 应用，FastAPI + PostgreSQL pgvector + S3 + Next.js）
目标：自研 RAG 模块替代 AnythingLLM（已完成）
日期：2026-08-04 ~ 2026-08-07

---

# RAG 入库架构（消息队列版）

入库从「数据库 pending 轮询」升级为「Redis + Celery 消息队列」。

```
上传文件
  -> 保存到 RustFS/S3
  -> 写 File 记录
  -> 写 RagDocument(status=pending)   ← 状态表：只记录，不处理
  -> 投递 Celery 任务到 Redis          ← 调度层：只调度
  -> rag-worker 消费任务
  -> loader(MarkItDown) / splitter / embedder / vector_store
  -> 更新 RagDocument 状态(completed / failed)
```

## 三层职责划分

| 层 | 组件 | 职责 |
|----|------|------|
| 调度层 | Redis + Celery | 任务投递、重试、worker 并发消费、失败记录 |
| 状态与审计层 | PostgreSQL `rag_documents` | pending / processing / completed / failed、error_message、chunk_count、content_hash |
| 向量检索层 | PostgreSQL pgvector `rag_chunks` | 1024 维 embedding 向量、cosine_distance 检索 |

## 关键模块

| 文件 | 职责 |
|------|------|
| `rag/celery_app.py` | 创建 Celery app，配置 broker / result backend / 路由 |
| `rag/tasks.py` | 定义 `process_rag_document` 任务 + `enqueue_rag_document_task` 投递辅助 |
| `rag/task_worker.py` | `RagIndexingProcessor` 单任务处理器（不再轮询） |
| `rag/ingest_service.py` | 创建或重置 RagDocument 记录（幂等） |

## 为什么用消息队列

1. 上传接口不做 embedding —— 解析、切分、向量化耗时（可能数秒到数十秒），
   同步做会阻塞 HTTP 请求；投递队列后立即返回。
2. Redis/Celery 比「pending 轮询」更适合扩展 —— 轮询有固定的空转延迟、
   单进程吞吐受限；Celery 支持多 worker 并发消费、按队列水平扩展。
3. `rag_documents` 仍然是状态表 —— 队列只负责调度，业务可观测性
   （管理后台 /knowledge/status）靠状态表，两者解耦。
4. 失败任务重试 —— Celery 的 max_retries + countdown 自动延迟重试，
   可重试错误（网络、embedding 限流）由任务自己声明。
5. 多 worker 并发消费 —— `--concurrency=N` + Redis 队列天然支持水平扩展。

## 状态流转

```
pending ──worker 消费──> processing ──成功──> completed
   │                        │
   │                        ├─失败（可重试）──> Celery 延迟重试（retry_count +1）
   │                        │      └─达到 max_retries──> failed（文案：已达到最大重试次数）
   │                        ├─失败（不可重试）──> failed（可手动重试）
   │                        └─文件已被删除──> skipped（不算失败、不重试）
   └── /knowledge/sync 手动重试：failed + pending 重置为 pending，retry_count 清零
   └── /knowledge/rebuild 全量补齐：扫描 files 表，补建/重投缺失的入库任务
```

`rag_documents` 状态字段：

| 字段 | 含义 |
|------|------|
| status | pending / processing / completed / failed / skipped |
| retry_count | 累计重试次数（手动重试时清零） |
| chunk_count | 索引生成的分块数 |
| error_message | 脱敏后的错误信息（不含 API Key；skipped 时为跳过原因） |
| content_hash | 文档内容 SHA256 |
| queued_at | 入队时间 |
| processing_started_at | worker 开始处理时间 |
| completed_at | 完成时间 |
| failed_at | 失败时间 |

> **skipped 语义**：文件被删除后，旧队列消息到达时不会把任务标记为 failed，
> 而是置为 skipped，管理端不将其计入失败数，也不参与自动重试。

## 启动与排查

启动后应包含 redis 和 rag-worker 两个新服务：

```bash
# 查看所有服务状态（应含 redis、rag-worker）
./start_wiki.sh status
# 查看 wiki-web / wiki-backend 日志
./start_wiki.sh logs
# 查看 RAG 入库 worker 日志
docker compose logs rag-worker
# 查看 Redis 日志
docker compose logs redis
```

**已有数据库升级**：后端启动时自动执行幂等迁移
（`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`），无需手动跑 SQL，也不会重复加列。

---

# 第一步：定义 RAG 数据结构（schemas.py）

## 1. 为什么要先定义统一的数据结构

AnythingLLM 内部处理文档的流程是：
原始文件(pdf/md/txt) → Loader加载 → Splitter切分 → Embedding向量化 → 向量库 → Retriever检索

每个环节都需要传递数据。如果没有统一的数据结构：
- Loader 返回 str，Splitter 返回 list[str]，Embedding 不知道片段来自哪个文档
- 检索时命中了片段，但找不到原始文档的标题、路径
- 后面每加一个环节都要改所有调用方

## 2. 第一阶段最少需要哪几个对象

| 对象 | 含义 |
|------|------|
| Document | 一份完整的原始文档（加载后的文本 + 元信息） |
| Chunk | 从 Document 切出来的一个文本片段 |

## 3. Document 和 Chunk 分别代表什么（结合 AnythingLLM 流程）

- Document = AnythingLLM 内部 loader 解析出一份文件后的"全文 + 元信息"。对应 files 表，内容是 get_file_content(storage_key) 拿到的文本。
- Chunk = Document 被 splitter 切出来的小段，最终被 embedding 成向量存入向量库。

## 4-7. 代码和字段解释

```python
@dataclass
class Document:
    doc_id: str      # uuid4，Chunk 靠它关联回 Document
    title: str       # 文件名，检索结果展示来源
    content: str     # 全文，Splitter 从这里切
    metadata: dict   # file_id、storage_key，检索时透传

@dataclass
class Chunk:
    chunk_id: str    # uuid4，向量库唯一 key
    doc_id: str      # 关联 Document
    text: str        # 片段文本，Embedding 输入
    metadata: dict   # 继承自 Document
```

验证：python -c "from rag.schemas import Document, Chunk; doc=Document.create(title='t',content='h'); chunk=Chunk.create(doc_id=doc.doc_id,text='h'); print(chunk.doc_id==doc.doc_id)"

---

# 第二步：文本切分（splitter.py）

## 1-5. 核心概念

Splitter 是第二环：Document.content → list[Chunk]。必须切分因为 embedding 模型有输入长度限制（8191 token）。

AnythingLLM 用 LangChain 的 RecursiveCharacterTextSplitter，分隔符递归降级：\n\n → \n → 空格 → 字符。

chunkSize（片段上限）=500，chunkOverlap（相邻重叠）=50——防止边界语义断裂。

## 6-10. 代码

```python
_SEPARATORS = ["\n\n", "\n", "。", " ", ""]

def split_text(text, chunk_size, chunk_overlap):
    """递归分隔符降级切分"""
    separator = _SEPARATORS[-1]
    for sep in _SEPARATORS:
        if sep == "": break
        if sep in text: separator = sep; break
    splits = text.split(separator) if separator else list(text)
    chunks = []; current = ""
    for split in splits:
        if current and len(current)+len(separator)+len(split) > chunk_size:
            chunks.append(current)
            current = (current[-chunk_overlap:]+separator+split) if chunk_overlap>0 else split
        else:
            current = (current+separator+split) if current else split
    if current: chunks.append(current)
    return chunks

class TextSplitter:
    def split(self, document):
        texts = split_text(document.content, self.chunk_size, self.chunk_overlap)
        return [Chunk.create(doc_id=document.doc_id, text=t, metadata={**document.metadata}) for t in texts]
```

---

# 第三步：Embedding（embedding.py）

## 核心

Embedder 把 Chunk.text → list[float]（1024 维，阿里 text-embedding-v3）。语义相近的文本向量距离也近，这是检索的基础。

AnythingLLM 有 20+ provider，但所有 OpenAI 兼容的代码都一样：POST /v1/embeddings。

```python
class Embedder:
    async def embed(self, chunks: list[Chunk]) -> list[list[float]]:
        texts = [c.text for c in chunks]
        r = await client.post(f"{api_url}/embeddings",
            json={"model": model, "input": texts})
        return [item["embedding"] for item in sorted(r.json()["data"], key=lambda x:x["index"])]
```

---

# 第四步：向量存储（vector_store.py + ORM）

## 设计

两张表（非三张）：向量放 Chunk 表里，因为 1:1 关系不需要范式化。pgvector 原生支持这种设计。

```sql
rag_documents(id, file_id FK, doc_id, title, content_hash, status, chunk_count)
rag_chunks(id, document_id FK, chunk_id, text, embedding vector(1024), metadata JSONB)
```

```python
class VectorStore:
    async def insert(document, chunks, vectors)      # 写入
    async def search(query_vector, top_k=5)           # 余弦相似度
    async def delete_by_document(document)             # 删除
```

部署前：CREATE EXTENSION IF NOT EXISTS vector;

---

# 第五步：检索（retriever.py）

Retriever 编排 Embedder + VectorStore：用户问题 → query_vector → VectorStore.search() → list[RetrievalResult]。

AnythingLLM 的 performSimilaritySearch 接收原始文本而非向量——隐藏 embedding 细节、保证模型一致性。

```python
class Retriever:
    async def retrieve(self, query):
        qv = await self.embedder.embed([Chunk(text=query)])
        rows = await self.vector_store.search(qv[0])
        return [RetrievalResult(chunk_id=r["chunk_id"], ...) for r in rows]

    def format_context(self, results):
        return "\n\n".join(f"[来源 {i}] {r.metadata.get('title','')}\n{r.text}"
                          for i,r in enumerate(results,1))
```

---

# 第六步：异步入库（消息队列）

三个模块协作，不再使用 while 轮询：

```python
# ingest_service.py —— 只创建/重置 RagDocument(status=pending)，不跑流水线
class IngestService:
    async def ingest(self, file_id):
        doc = RagDocument(file_id=file_id, title=file.title, status="pending")
        db.add(doc); return doc

# tasks.py —— Celery 任务，接收 rag_document_id，调用处理器
@celery_app.task(bind=True, max_retries=..., name="rag.tasks.process_rag_document")
def process_rag_document(self, rag_document_id):
    status = asyncio.run(RagIndexingProcessor().process(rag_document_id))
    return {"rag_document_id": rag_document_id, "status": status}

# task_worker.py —— 单任务处理器（无轮询），原子抢占 pending/failed → processing
class RagIndexingProcessor:
    async def process(self, rag_document_id):
        if not await self._claim_processing(rag_document_id):
            return "skipped"
        async with AsyncSessionLocal() as db:
            doc = await self._load_document(db, rag_document_id)
            await self._run_pipeline(db, doc)
            doc.status = "completed"; await db.commit()
```

---

# 第七步：架构审查 + loader 修复

发现问题：TaskWorker 绕过 loader 裸读 S3 bytes + decode("utf-8")。修复为统一调用 loader.load_bytes()。

---

# 第八步：MarkItDown 集成

Microsoft MarkItDown — 一行 API 覆盖 PDF/DOCX/PPTX/XLSX/HTML/图片/音频/EPUB/CSV，输出统一 Markdown：

```python
from markitdown import MarkItDown, StreamInfo
class DocumentLoader:
    def _convert(self, file_name, content, metadata):
        result = self._md.convert_stream(io.BytesIO(content),
            stream_info=StreamInfo(extension=suffix, filename=file_name))
        return Document.create(title=file_name, content=result.text_content, metadata=metadata)
```

---

# 第九步：Prompt 组装（prompt_builder.py）

```python
class PromptBuilder:
    def build(self, question, context="", chat_history=None):
        messages = []
        if self.system_prompt:
            messages.append({"role":"system","content":self.system_prompt})
        if chat_history: messages.extend(chat_history)
        messages.append({"role":"user","content": f"参考资料：\n{context}\n\n问题：{question}"})
        return messages  # OpenAI messages 格式
```

---

# 第十步：LLM 调用（llm.py）

```python
class LLM:
    async def chat(self, messages):         # 非流式 → str
    async def chat_stream(self, messages):  # 流式 → AsyncGenerator[str]
```

---

# 第十一步：聊天编排（chat_service.py）

查询链路唯一入口：
```python
class ChatService:
    async def ask_stream(self, question, db):
        results = await retriever.retrieve(question)
        context = retriever.format_context(results)
        messages = PromptBuilder().build(question, context)
        async for token in LLM().chat_stream(messages):
            yield token
```

---

# 第十二步：FastAPI 路由

POST /api/v1/rag/ingest {"file_id": 42} → {"id":1, "status":"pending"}
POST /api/v1/chat/rag/stream {"message":"..."} → SSE 流式回答

---

# 第十三步：Docker 部署

- 镜像: postgres:18 → pgvector/pgvector:pg18
- Dockerfile: COPY rag ./rag + RUN uv pip install pgvector 'markitdown[all]'

---

# 完整架构对照

| AnythingLLM | 自研模块 | 状态 |
|---|---|---|
| loader | loader.py + MarkItDown | ✅ |
| TextSplitter | splitter.py | ✅ |
| EmbeddingEngines | embedding.py | ✅ |
| VectorDbProviders | vector_store.py (pgvector) | ✅ |
| performSimilaritySearch | retriever.py | ✅ |
| addDocumentToNamespace | ingest_service + task_worker | ✅ |
| constructPrompt | prompt_builder.py | ✅ |
| AiProviders | llm.py | ✅ |
| Stream orchestration | chat_service.py | ✅ |
| Rerank/History/Memories | ❌ v1 不做 | - |

## 最终目录

```
wiki-backend/rag/
├── schemas.py, loader.py, splitter.py, embedding.py
├── vector_store.py, retriever.py
├── ingest_service.py, task_worker.py
├── prompt_builder.py, llm.py, chat_service.py
app/api/v1/rag.py
app/models.py (+RagDocument, +RagChunk)
```
