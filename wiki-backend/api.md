# API Reference

Base URL: `http://localhost:8000`

## Public Endpoints

### Get Directory Tree

Returns the complete nested directory structure.

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
        "children": [...]
      }
    ]
  }
]
```

---

### Resolve Path

Get node information and file content by path.

```http
GET /api/v1/nodes/resolve/{path}
```

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| path | string | Logical path (e.g., `docs/guide/intro`) |

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
| File Extension | content_type | Description |
|----------------|--------------|-------------|
| `.md`, `.txt`, `.html` | `"text"` | Raw text content |
| `.pdf`, `.docx` | `"base64"` | Base64 encoded binary |

---

## Admin Endpoints (Protected)

> ⚠️ All admin endpoints require Bearer token authentication (dynamic JWT token obtained from `/login`).

**Header:**
```
Authorization: Bearer <JWT_TOKEN>
```

---

### Sync Directory

Trigger a scan of WIKI_ROOT and sync to database.

```http
POST /api/v1/admin/sync
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/admin/sync \
  -H "Authorization: Bearer your-jwt-token"
```

**Response:**
```json
{
  "success": true,
  "message": "Sync completed successfully",
  "created": 5,
  "updated": 0,
  "deleted": 0,
  "skipped": 10
}
```

---

### Upload File

Upload a markdown file to the wiki.

```http
POST /api/v1/admin/upload
Content-Type: multipart/form-data
```

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| file | file | File to upload (.md, .html, .docx, .txt, .pdf) |
| parent_id | int | Optional parent folder ID |

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/admin/upload \
  -H "Authorization: Bearer your-jwt-token" \
  -F "file=@./my-article.md" \
  -F "parent_id=1"
```

**Response:**
```json
{
  "success": true,
  "message": "File uploaded successfully: docs/my-article",
  "node": {
    "id": 10,
    "title": "My Article",
    "slug": "my-article",
    "full_path": "docs/my-article",
    "node_type": "FILE"
  }
}
```

---

### Delete File/Folder

Delete a node and optionally its physical file.

```http
DELETE /api/v1/admin/delete/{node_id}
```

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| node_id | int | ID of the node to delete |
| delete_physical | bool | Delete physical file (default: true) |

**Example:**
```bash
curl -X DELETE "http://localhost:8000/api/v1/admin/delete/5?delete_physical=true" \
  -H "Authorization: Bearer your-jwt-token"
```

**Response:**
```json
{
  "success": true,
  "message": "Deleted successfully: docs/my-article",
  "deleted_path": "docs/my-article",
  "physical_deleted": true
}
```

---

## Error Responses

### 401 Unauthorized
```json
{
  "detail": "Not authenticated"
}
```

### 404 Not Found
```json
{
  "detail": "Node not found: invalid/path"
}
```

### 400 Bad Request
```json
{
  "detail": "Only .md files are allowed"
}
```
