# Wiki App 项目架构需求说明书 (PRD for AI Agent)

> ⚠️ **历史文档**：本文档描述的是早期基于磁盘扫描（`Node` 模型 + `/admin/sync`）的架构。
> 当前实现已改为 RustFS/S3 存储 + `Folder`/`File` 模型 + 自研 RAG 模块（`wiki-backend/rag/`），
> 入库走 Redis + Celery 消息队列。请以 `api.md` 与 `RAG.md` 为准。

## 1. 系统概述

* **技术栈**: FastAPI (Backend) + Next.js App Router (Frontend) + SQLAlchemy (ORM).
* **核心逻辑**: 采用“混合存储架构”。物理文件存放在磁盘 `WIKI_ROOT`，数据库 `nodes` 表作为索引层，存储层级关系与 **全量路径索引 (Full-path Index)**。
* **事实标准**: 磁盘文件为准。通过扫描同步算法将文件结构映射至数据库。

## 2. 数据库 Schema (SQLAlchemy 风格)

```python
class Node(Base):
    __tablename__ = "nodes"
    
    id = Column(Integer, primary_key=True)
    parent_id = Column(Integer, ForeignKey("nodes.id"), nullable=True)
    node_type = Column(Enum("FOLDER", "FILE"), nullable=False)
    title = Column(String(255), nullable=False) # 界面显示名
    slug = Column(String(100), nullable=False)  # 当前层级路径段
    full_path = Column(String(500), unique=True, index=True) # 索引键: engineering/backend/fastapi
    file_path = Column(String(500), unique=True) # 物理路径: /data/wiki/01_eng/02_back/fastapi.md
    sort_order = Column(Integer, default=0)
    
    # 建立自引用关系
    children = relationship("Node", backref=backref("parent", remote_side=[id]))

```

## 3. 后端 API 契约设计 (FastAPI)

| 终点 (Endpoint) | 方法 | 功能 | 关键参数 |
| --- | --- | --- | --- |
| `/api/v1/nodes/tree` | GET | 返回嵌套的目录树 | 无 |
| `/api/v1/nodes/resolve/{path:path}` | GET | **核心读取接口** | 获取 full_path 匹配的节点信息及文件内容 |
| `/api/v1/admin/sync` | POST | 触发磁盘扫描同步 | 递归扫描 `WIKI_ROOT` 并更新 DB |
| `/api/v1/admin/upload` | POST | 上传文件并写入 DB | 包含 `parent_id` 和 Multipart 文件 |

## 4. 核心逻辑实现要点

### A. 路径解析逻辑 (Resolution)

* **输入**: 字符串 `a/b/c`。
* **逻辑**: `SELECT * FROM nodes WHERE full_path = :path LIMIT 1`。
* **安全**: 读取文件前需校验 `file_path` 是否在 `WIKI_ROOT` 范围内。

### B. 扫描同步算法 (Syncing)

1. **递归遍历**: 使用 `pathlib.Path.rglob("*.md")` 遍历目录。
2. **路径标准化**: 将物理路径转为逻辑 `full_path`。
3. **增量更新**:
* 若 `full_path` 不在 DB 中 -> 创建节点（递归创建缺失的父文件夹）。
* 若 DB 记录在磁盘不存在 -> 删除记录。
* 若文件修改时间变化 -> 更新元数据。


## 5. 目录结构建议

```text
.
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── models.py        # 数据库模型
│   │   ├── schemas.py       # Pydantic 模型
│   │   ├── crud.py          # 数据库操作
│   │   ├── scanner.py       # 磁盘同步逻辑
│   │   └── api/             # 路由模块
│   └── wiki_storage/        # 物理 Markdown 存储根目录
```

---