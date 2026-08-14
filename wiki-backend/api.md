# API Reference

Base URL: `http://localhost:8000`

---

## 认证

### 登录

```http
POST /api/v1/auth/login
```

**Body:**
```json
{
  "username": "admin",
  "password": "your-password"
}
```

**Response:**
```json
{
  "access_token": "<JWT>",
  "username": "admin",
  "role": "admin"
}
```

### 当前用户

```http
GET /api/v1/auth/me
Authorization: Bearer <JWT>
```

---

## Public Endpoints（无需认证）

### Get Directory Tree

返回完整嵌套目录结构。

```http
GET /api/v1/nodes/tree
```

**Response:**
```json
[
  {
    "id": 1,
    "title": "Docs",
    "slug": "docs",
    "full_path": "docs",
    "node_type": "FOLDER",
    "sort_order": 0,
    "children": [
      {
        "id": 2,
        "title": "Guide",
        "full_path": "docs/guide",
        "node_type": "FOLDER",
        "children": []
      }
    ]
  }
]
```

---

### Resolve Path

按路径获取节点信息与文件内容。

```http
GET /api/v1/nodes/resolve/{path}
```

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| path | string | 逻辑路径（如 `docs/guide/intro`） |

**Response:**
```json
{
  "id": 4,
  "title": "Intro",
  "slug": "intro",
  "full_path": "docs/guide/intro",
  "node_type": "FILE",
  "file_path": "/path/to/wiki_storage/docs/guide/01_intro.md",
  "content": "# Getting Started\n...",
  "content_type": "text"
}
```

**Content Types:**
| 扩展名 | content_type | 说明 |
|--------|--------------|------|
| `.md`, `.txt`, `.html` | `"text"` | 原始文本 |
| `.pdf`, `.docx` | `"base64"` | Base64 编码的二进制 |

---

## Admin Endpoints（需 Bearer 认证）

> ⚠️ 所有管理端接口都需要 `Authorization: Bearer <JWT>`。

---

### Upload File

上传文件到 Wiki。文件写入 RustFS/S3 后，会创建 `rag_documents` 记录并异步投递 Celery 入库任务。

```http
POST /api/v1/admin/upload
Content-Type: multipart/form-data
```

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| file | file | 允许 `.md`, `.html`, `.docx`, `.txt`, `.pdf` |
| folder_id | int | 可选，父文件夹 ID（0 表示根目录） |

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/admin/upload \
  -H "Authorization: Bearer <JWT>" \
  -F "file=@./my-article.md" \
  -F "folder_id=1"
```

**成功响应（入队成功）:**
```json
{
  "success": true,
  "message": "File uploaded successfully: docs/my-article. RAG indexing task queued.",
  "file": {
    "id": 10,
    "folder_id": 1,
    "title": "My Article",
    "slug": "my-article",
    "full_path": "docs/my-article",
    "sort_order": 0
  }
}
```

**成功响应（入队失败）:**
文件已成功写入存储，但 Redis 不可用导致 Celery 任务投递失败。
此时 `rag_documents` 记录会被标记为 `failed`（error_message 注明「Celery 任务投递失败（Redis 不可用）」），
`message` 会明确提示「知识库入队失败」，便于管理端在 Redis 恢复后通过 `/knowledge/sync` 手动重试。

```json
{
  "success": true,
  "message": "文件上传成功，但知识库入队失败: docs/my-article",
  "file": { "...": "..." }
}
```

---

### Create Folder

```http
POST /api/v1/admin/folder
```

**Body:**
```json
{ "title": "New Folder", "parent_id": 1 }
```

---

### Delete File / Folder

删除节点并清理 RAG 索引（物理文件可选）。

```http
DELETE /api/v1/admin/delete/{item_type}/{item_id}
```

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| item_type | string | `file` 或 `folder` |
| item_id | int | 节点 ID |
| delete_physical | bool | 是否删除物理文件（默认 true） |

**Example:**
```bash
curl -X DELETE "http://localhost:8000/api/v1/admin/delete/file/5?delete_physical=true" \
  -H "Authorization: Bearer <JWT>"
```

**Response:**
```json
{
  "success": true,
  "message": "Deleted successfully: docs/my-article. RAG index cleaned.",
  "deleted_path": "docs/my-article",
  "physical_deleted": true
}
```

---

### RAG 知识库状态

返回自研 RAG 索引的实时状态统计。

```http
GET /api/v1/admin/knowledge/status
```

**Response:**
```json
{
  "success": true,
  "pending": 2,
  "processing": 1,
  "completed": 42,
  "failed": 1,
  "skipped": 3,
  "latest_error": "【将自动重试】Embedding API 暂时不可用: HTTP 429"
}
```

> `skipped` 表示任务被跳过（例如文件已被删除），不属于失败，不会计入 failed。

---

### RAG 知识库手动重试

把 `failed` 和 `pending` 的文档重置为 `pending`（retry_count 清零），并批量重新投递 Celery 任务。
`pending` 可能因 Redis 重启等原因丢失队列消息，因此一并重投；`processing` 正在被 worker 处理则跳过保护；`skipped`（文件已删除）重试无意义，不处理。

```http
POST /api/v1/admin/knowledge/sync
```

**Response:**
```json
{
  "success": true,
  "message": "Reset 3 failed/pending documents to pending.",
  "scheduled": 3,
  "enqueued": 3,
  "failed_enqueue": 0
}
```

---

### RAG 知识库全量补齐

扫描 `files` 表中所有 Wiki 文件，补齐缺失的 RAG 入库任务：

- 无 `RagDocument` 的文件 → 创建记录并投递（`created`）
- 已有记录但状态为 `failed`/`pending` → 重置并重新投递（`requeued`）
- 状态为 `completed`/`processing`/`skipped` → 跳过（`skipped`）
- 投递失败 → 标记 failed（`failed_enqueue`）

```http
POST /api/v1/admin/knowledge/rebuild
```

**Response:**
```json
{
  "success": true,
  "message": "Rebuild finished: created 5, requeued 2, skipped 10.",
  "created": 5,
  "requeued": 2,
  "skipped": 10,
  "enqueued": 7,
  "failed_enqueue": 0
}
```

---

### RAG 配置可用性检查

轻量状态接口，判断 `LLM_API_KEY`、`EMBEDDING_API_KEY`、Redis/Celery 队列配置是否具备。
只返回 boolean 与缺失项名称，不输出任何密钥真实值。

```http
GET /api/v1/rag/config-status
```

**Response:**
```json
{
  "success": true,
  "ready": true,
  "missing": [],
  "llm_configured": true,
  "embedding_configured": true,
  "queue_configured": true
}
```

---

### 同步历史

返回最近的知识库入库任务历史（含状态、重试次数、错误信息、时间戳）。

```http
GET /api/v1/admin/sync-history?limit=50
```

**Response 字段:** `id`, `doc_id`, `file_id`, `title`, `full_path`, `storage_key`,
`status`, `retry_count`, `chunk_count`, `error_message`, `content_hash`,
`queued_at`, `processing_started_at`, `completed_at`, `failed_at`, `created_at`, `updated_at`。

---

### Dashboard 统计

```http
GET /api/v1/admin/stats
```

---

### 用户管理 / 会话审计

```http
GET    /api/v1/admin/users
POST   /api/v1/admin/users
PUT    /api/v1/admin/users/{user_id}
DELETE /api/v1/admin/users/{user_id}
GET    /api/v1/admin/chat-sessions
GET    /api/v1/admin/chat-sessions/{session_id}/messages
```

---

## Error Responses

### 401 Unauthorized
```json
{ "detail": "Not authenticated" }
```

### 404 Not Found
```json
{ "detail": "Node not found: invalid/path" }
```

### 400 Bad Request
```json
{ "detail": "File type not allowed. Allowed types: .md, .html, .docx, .txt, .pdf" }
```

---

## 排查命令

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

## 升级与构建说明

- **历史目录名**：`wiki-backend/anythingllm/` 只是历史遗留的目录名，
  目录内的 `compose.yml` / `compose.dev.yml` 编排的是当前 RAG 版服务
  （wiki-web / wiki-backend / postgres / rustfs / redis / rag-worker），
  不再运行 AnythingLLM。
- **数据库迁移**：后端启动时会自动对已有数据库执行幂等迁移
  （`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`，见
  `migrations/0001_add_rag_queue_fields.sql` 与 `app/core/database.py` 的
  `_apply_rag_queue_migration`）。已有数据库无需手动执行 SQL，也不会重复加列。
- **前端构建**：前端改动需重新构建：
  ```bash
  cd wiki-web && npm run lint && npm run build
  ```
  或通过 Compose 重新构建镜像：
  ```bash
  # 等价于 docker compose -f wiki-backend/anythingllm/compose.yml up -d --build
  ./start_wiki.sh restart
  ```
