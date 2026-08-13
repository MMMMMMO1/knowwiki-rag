# Wiki Backend

A FastAPI backend for a wiki application with file-based content management.

## Features

- 🗂️ **Hybrid Storage** - Files on disk + PostgreSQL index
- 🔄 **Directory Sync** - Auto-scan markdown files to database
- 📁 **Hierarchical Structure** - Self-referential Node model
- 🔐 **Admin Authentication** - Bearer token for admin APIs
- 🚀 **Async Support** - Built with async SQLAlchemy

## Tech Stack

| Component | Technology |
|-----------|------------|
| Framework | FastAPI |
| ORM | SQLAlchemy 2.0 (async) |
| Database | PostgreSQL |
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
│   ├── main.py           # FastAPI entry
│   ├── models.py         # Node model
│   ├── schemas.py        # Pydantic schemas
│   ├── crud.py           # DB operations
│   ├── scanner.py        # Directory sync
│   ├── api/v1/           # API routes
│   │   ├── nodes.py      # Public endpoints
│   │   └── admin.py      # Protected endpoints
│   └── core/
│       ├── config.py     # Settings
│       ├── database.py   # DB connection
│       └── security.py   # Auth
├── wiki_storage/         # Markdown files
├── rag/                  # 自研 RAG 文档索引与问答模块
└── app/core/config.py    # Settings loaded from repository root .env
```
