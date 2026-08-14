# Wiki

这是一个前后端分离的 Wiki 应用，包含 Next.js 前端、FastAPI 后端、自研 RAG 知识库、PostgreSQL（pgvector）、Redis/Celery 消息队列与 RustFS。当前推荐使用仓库根目录的启动脚本统一构建和运行容器环境。

> **迁移说明**：项目原本使用 AnythingLLM 作为文档索引和聊天引擎，现已全面替换为自研 RAG 模块（`wiki-backend/rag/`）。AnythingLLM 容器、代码和配置已清理。
>
> **分支说明**：`rag-rewrite` 是自研 RAG 的独立版本分支，技术栈为自研 RAG + Redis/Celery 消息队列 + PostgreSQL pgvector，带管理端状态可观测，不依赖 AnythingLLM。

## 项目结构

- `wiki-web/`：Next.js 前端，包含页面、管理端接口代理、聊天组件和静态资源。
- `wiki-backend/`：FastAPI 后端，负责 Wiki 节点、文件上传、S3/RustFS 存储、RAG 知识库入库等接口。
  - `wiki-backend/rag/`：自研 RAG 模块（文档加载 → 切分 → 嵌入 → 向量检索 → LLM 问答）。
  - `rag/celery_app.py` + `rag/tasks.py`：Celery 任务调度（RAG 入库）。
  - `rag/task_worker.py`：单任务处理器（RagIndexingProcessor）。
- `wiki-backend/anythingllm/compose.yml`：默认容器编排文件（PostgreSQL、Redis、RustFS、Wiki 前后端、rag-worker）。`anythingllm` 仅为历史目录名，当前不再运行 AnythingLLM。
- `wiki-backend/anythingllm/compose.dev.yml`：dev 模式覆盖文件（历史兼容，当前 dev 模式与默认模式一致）。
- `start.sh` / `start_wiki.sh`：仓库根目录的一键启动、停止、查看状态和日志入口。

## RAG 入库架构

上传文件后，入库走 Redis + Celery 消息队列，由独立 worker 异步消费：

```
上传文件 → RustFS/S3 → File 记录 → RagDocument(pending) → Celery 投递 → rag-worker 消费
         → loader/splitter/embedder/vector_store → RagDocument(completed/failed)
```

- **Redis/Celery**：任务调度层（投递、重试、并发消费）。
- **PostgreSQL rag_documents**：状态与审计层（pending/processing/completed/failed）。
- **PostgreSQL pgvector rag_chunks**：向量检索层。

### 状态流转

```
pending → processing → completed
   │            └── 失败 → failed（可手动重试）
   └── /knowledge/sync 手动重试：failed/pending → pending
```

`rag_documents` 记录 retry_count、chunk_count、content_hash、error_message，
以及 queued_at / processing_started_at / completed_at / failed_at 等时间戳。

### 常用排查命令

```bash
# 查看所有服务状态（应含 redis、rag-worker）
./start_wiki.sh status
# 查看 wiki-web / wiki-backend 日志
./start_wiki.sh logs
# 查看 RAG 入库 worker 日志
docker compose logs rag-worker
```

## 快速启动

默认模式只开放 Wiki Web 端口，后端、数据库、Redis、RustFS 均只允许 Docker 内部网络访问。

首次启动前先从根目录模板创建本地配置，并填写 `ADMIN_USERNAME` / `ADMIN_PASSWORD`、数据库密码、S3 密钥、LLM/Embedding API Key 等值：

```bash
cp .env.example .env
```

```bash
./start.sh start
```

启动后访问：

```text
http://127.0.0.1:3000
```

常用命令：

```bash
./start.sh status
./start.sh logs
./start.sh stop
./start.sh restart
```

## Dev 模式

Dev 模式当前与默认模式相同（历史兼容，不再额外开放调试端口）。如需本地调试后端或 RAG 模块，请直接在宿主机运行：

```bash
cd wiki-backend && uv run uvicorn app.main:app --reload
```

## 端口策略

默认模式：

- `127.0.0.1:3000` -> `wiki-web:3000`
- `wiki-backend:8000` 仅 Docker 内部访问
- `postgres:5432` 仅 Docker 内部访问
- `rustfs:9000/9001` 仅 Docker 内部访问

dev 模式：

- 端口策略与默认模式相同（历史兼容保留，不再额外开放端口）。

## 构建说明

`./start.sh start` 和 `./start.sh dev` 会通过 Docker Compose 构建：

- `wiki-web:latest`
- `wiki-backend:latest`

前端使用 Next.js standalone 产物运行；后端使用 `uv` 根据 `uv.lock` 同步 Python 依赖。

## 配置与安全

敏感配置统一保存在仓库根目录 `.env`，模板为 `.env.example`；`wiki-backend/.env` 与 `wiki-web/.env` 不再参与运行。默认容器模式通过 Next.js rewrite 将浏览器请求代理到 Docker 内部后端：

- `/wiki-api/*` -> `wiki-backend:8000`

聊天和文件上传走 RAG 链路：前端调用 `/api/chat/stream`（SSE 流式）或 `/api/admin/upload`，由 FastAPI 在内部完成文档索引和向量检索，不依赖外部服务。
