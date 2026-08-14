# Wiki Backend

A FastAPI backend for a wiki application with file-based content management.

## Features

- 🗂️ **Hybrid Storage** - Files on RustFS/S3 + PostgreSQL index
- 🔍 **自研 RAG 知识库** - 文档解析 → 切分 → 嵌入 → 向量检索 → LLM 问答
- 📁 **Hierarchical Structure** - Self-referential Folder/File model
- 🔐 **Admin Authentication** - Bearer token for admin APIs
- 🚀 **Async Support** - Built with async SQLAlchemy
- ⚙️ **消息队列入库** - Redis + Celery 异步消费，失败自动重试

## Tech Stack

| Component | Technology |
|-----------|------------|
| Framework | FastAPI |
| ORM | SQLAlchemy 2.0 (async) |
| Database | PostgreSQL 17 + pgvector |
| Queue | Redis + Celery |
| Package Manager | uv |

## Quick Start

### 1. Install Dependencies

```bash
uv sync
```

### 2. Configure Environment

后端不再使用 `wiki-backend/.env`。请在仓库根目录从 `.env.example` 创建 `.env`，并按需填写数据库、S3、管理员 token、LLM 与 Embedding API 配置：

```bash
cp ../.env.example ../.env
```

### 3. Run Server

```bash
uv run uvicorn app.main:app --reload
```

## Documentation

| Document | Description |
|----------|-------------|
| [API Reference](./api.md) | Complete API documentation |
| [Swagger UI](http://localhost:8000/docs) | Interactive API docs |
| [ReDoc](http://localhost:8000/redoc) | Alternative API docs |
| [RAG Design](./RAG.md) | RAG 自研模块设计与迁移说明 |

## Project Structure

```
wiki-backend/
├── app/
│   ├── main.py           # FastAPI entry（含启动时重置僵尸入库任务）
│   ├── models.py         # Folder/File/User/RagDocument/RagChunk 模型
│   ├── schemas.py        # Pydantic schemas
│   ├── crud.py           # DB operations
│   ├── scanner.py        # 文件路径规范化（normalize_slug 等辅助函数）
│   ├── api/v1/           # API routes
│   │   ├── nodes.py      # Public endpoints（目录树/路径解析）
│   │   ├── auth.py       # 登录 / 当前用户
│   │   └── admin.py      # 上传/删除/知识库状态/同步历史/用户管理
│   └── core/
│       ├── config.py     # Settings
│       ├── database.py   # DB connection
│       └── security.py   # Auth
├── rag/                  # 自研 RAG 文档索引与问答模块
│   ├── celery_app.py     # Celery app 配置（broker/result backend/路由）
│   ├── tasks.py          # process_rag_document 任务 + 投递辅助
│   ├── task_worker.py    # RagIndexingProcessor 单任务处理器
│   ├── ingest_service.py # 创建/重置 RagDocument（幂等）
│   ├── loader.py         # MarkItDown 文档解析
│   ├── splitter.py       # 文本切分
│   ├── embedding.py      # Embedding 向量化
│   ├── vector_store.py   # pgvector 写入与检索
│   └── retriever.py      # 检索编排
└── migrations/           # SQL 迁移脚本
```
