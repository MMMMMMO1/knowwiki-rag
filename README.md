# Wiki

这是一个前后端分离的 Wiki 应用，包含 Next.js 前端、FastAPI 后端、AnythingLLM、PostgreSQL 与 RustFS。当前推荐使用仓库根目录的启动脚本统一构建和运行容器环境。

## 项目结构

- `wiki-web/`：Next.js 前端，包含页面、管理端接口代理、聊天组件和静态资源。
- `wiki-backend/`：FastAPI 后端，负责 Wiki 节点、文件上传、S3/RustFS 存储、AnythingLLM 同步等接口。
- `wiki-backend/anythingllm/compose.yml`：默认容器编排文件。
- `wiki-backend/anythingllm/compose.dev.yml`：dev 模式覆盖文件，用于临时开放 AnythingLLM 调试端口。
- `start.sh` / `start_wiki.sh`：仓库根目录的一键启动、停止、查看状态和日志入口。

## 快速启动

默认模式只开放 Wiki Web 端口，后端、数据库、RustFS、AnythingLLM 均只允许 Docker 内部网络访问。

首次启动前先从根目录模板创建本地配置，并填写 `ADMIN_USERNAME` / `ADMIN_PASSWORD`、`ANYTHINGLLM_API_KEY`、数据库密码、S3 密钥和 `NEXT_PUBLIC_CHATBOT_EMBED_ID` 等值：

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

调试 AnythingLLM 时使用 dev 模式。此模式会在默认 Web 端口之外，额外开放 AnythingLLM 端口。

```bash
./start.sh dev
```

默认访问地址：

```text
Wiki Web: http://127.0.0.1:3000
AnythingLLM: http://127.0.0.1:3001
```

可通过环境变量调整端口和绑定地址：

```bash
ANYTHINGLLM_PORT=3002 ./start.sh dev
ANYTHINGLLM_BIND_HOST=0.0.0.0 ./start.sh dev
```

## 端口策略

默认模式：

- `127.0.0.1:3000` -> `wiki-web:3000`
- `wiki-backend:8000` 仅 Docker 内部访问
- `anythingllm:3001` 仅 Docker 内部访问
- `postgres:5432` 仅 Docker 内部访问
- `rustfs:9000/9001` 仅 Docker 内部访问

dev 模式：

- 默认模式的端口保持不变
- 额外开放 `127.0.0.1:3001` -> `anythingllm:3001`

## 构建说明

`./start.sh start` 和 `./start.sh dev` 会通过 Docker Compose 构建：

- `wiki-web:latest`
- `wiki-backend:latest`

前端使用 Next.js standalone 产物运行；后端使用 `uv` 根据 `uv.lock` 同步 Python 依赖。

## 配置与安全

敏感配置统一保存在仓库根目录 `.env`，模板为 `.env.example`；`wiki-backend/.env` 与 `wiki-web/.env` 不再参与运行。`wiki-backend/anythingllm/.env` 由 AnythingLLM 自动维护，不属于 Wiki 统一配置。默认容器模式通过 Next.js rewrite 将浏览器请求代理到 Docker 内部后端：

- `/wiki-api/*` -> `wiki-backend:8000`

聊天与文件同步不开放 AnythingLLM 浏览器代理：前端调用 `/api/chat/*` 或 `/api/admin/upload`，再由 FastAPI 使用内部 `ANYTHINGLLM_API_URL` 和 `ANYTHINGLLM_API_KEY` 访问 AnythingLLM。
