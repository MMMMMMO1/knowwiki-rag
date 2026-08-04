# Wiki Web 项目结构与 API 总结

## 项目结构概览

本项目是一个基于 **Next.js (App Router)** 的全栈/前端项目，主要目录结构和功能如下：

- **`app/`**: 包含 Next.js 的路由（页面和 API）：
  - **`app/wiki/`**: 用于展示 wiki 页面内容。
  - **`app/admin/`**: 后台管理界面，进行文件的同步和上传等操作。
  - **`app/api/`**: Next.js 内部的 API 路由，主要用于管理端的鉴权和请求转发（详见下方API总结）。
- **`components/`**: 存放 React 业务及通用组件。例如：`Sidebar`, `Navbar`, `PDFViewer.tsx`, `TOC.tsx` 等。
- **`lib/`**: 工具函数和共享状态管理等：
  - `api.ts`: 封装了向后端获取树状结构和解析文件内容的请求。
  - `store.ts`: 可能用于 Zustand 等前端状态管理。
- **`types/`**: TypeScript 类型定义文件（如 `TreeNode`, `ResolvedNode`）。

---

## API 端点 (Endpoints) 总结

主要交互包含三类：**数据读取**（通过 Next.js API 路由代理到后端）、**聊天接口**（通过 Next.js API 路由代理到后端）和 **管理端操作**（通过 Next.js API 路由携带数据库用户 JWT 转发请求）。

### 1. 数据读取接口（需登录）
通常位于 `lib/api.ts` 中，通过 Next.js 本地 API 代理到 FastAPI 后端，并携带当前数据库用户 JWT。

| HTTP 方法 | 接口路径 | 描述 |
| --- | --- | --- |
| **GET** | `/api/nodes/tree` | 获取 Wiki 的树状目录结构 (`TreeNode[]`)。不使用缓存。|
| **GET** | `/api/nodes/resolve/{path}` | 根据节点路径解析并获取文件详情内容（含 markdown, PDF 链接等 `ResolvedNode`）。不使用缓存。 |

### 2. 聊天接口（需登录）
聊天面板只调用 Next.js 本地 API。后端会在 Docker 内部网络中访问 AnythingLLM，不需要开放 `/anythingllm-api` 给浏览器。

| HTTP 方法 | 接口路径 | 描述 |
| --- | --- | --- |
| **GET** | `/api/chat/history?session_id={sessionId}` | 获取当前 AnythingLLM embed 会话历史。 |
| **DELETE** | `/api/chat/history?session_id={sessionId}` | 清空当前 AnythingLLM embed 会话历史。 |
| **POST** | `/api/chat/stream` | 发送问题并返回 SSE 流式回答。 |

### 3. 管理页面接口 (Next.js 内部路由代理)
管理端所有修改操作通过 `app/api/admin` 中的 Next.js API 路由转发，后端统一校验数据库用户登录后签发的 JWT。
（调用时需在 `Authorization: Bearer <JWT>` 请求头中传入当前登录用户 Token）

| HTTP 方法 | 本地接口路径 (Next.js) | 目标后端路径 (转发) | 描述 |
| --- | --- | --- | --- |
| **POST** | `/api/admin/upload` | `/api/v1/admin/upload` | 上传新文件（FormData格式），Next.js 将 multipart 数据直接透传给后端，需要 JWT 鉴权。 |
| **DELETE** | `/api/admin/delete/[nodeId]` | `/api/v1/admin/delete/{nodeId}` | 删除指定节点。URL支持参数 `?delete_physical=true\|false`，控制是否物理删除。 |

### 重构建议 (基于 Ant Design)
1. 安装 `antd` (`npm install antd` 或 `yarn add antd`)。
2. 配置应用级别的 `AntdRegistry` 以保证 Server Components 下由于 CSS-in-JS 的兼容性问题渲染正常 (Next.js App router 需要封装专门的 provider 来承载 Ant Design 样式)。
3. 可以使用 Ant Design 的 `Layout` (Header, Sider, Content) 来替换现有的布局逻辑。
4. API 依旧可以保留使用原有的 `fetch` 方式，也可以结合 `ahooks` (`useRequest`)、`swr` 或 `@tanstack/react-query` 统一管理请求状态。
