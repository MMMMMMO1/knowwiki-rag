# RAG 替代 AnythingLLM — 完整教学对话

项目：wiki-main（Wiki 应用，FastAPI + PostgreSQL + S3 + Next.js）
目标：自研 RAG 模块替代 AnythingLLM
日期：2026-08-04 ~ 2026-08-07

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

Embedder 把 Chunk.text → list[float]（1536维）。语义相近的文本向量距离也近，这是检索的基础。

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
rag_chunks(id, document_id FK, chunk_id, text, embedding vector(1536), metadata JSONB)
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

# 第六步：异步入库

两个新模块（不使用消息队列）：

```python
class IngestService:
    async def ingest(self, file_id):
        # 只创建 RagDocument(status=pending)，不跑流水线
        doc = RagDocument(file_id=file_id, title=file.title, status="pending")
        db.add(doc); return doc

class TaskWorker:
    async def run(self):
        while True:
            doc = await get_pending_document()  # with_for_update(skip_locked=True)
            if not doc: await sleep(1); continue
            doc.status = "processing"
            content = await get_file_content(storage_key)
            document = loader.load_bytes(title, content)  # 统一入口
            chunks = splitter.split(document)
            vectors = await embedder.embed(chunks)
            await store.insert(doc, chunks, vectors)
            doc.status = "completed"
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
