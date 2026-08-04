/**
 * Backend tree API response types.
 *
 * The backend returns a separated folder/file structure:
 *   Folder → { id, title, slug, full_path, sort_order, children: Folder[], files: TreeFile[] }
 *   File   → { id, title, slug, full_path, sort_order, storage_key }
 */

export interface TreeFile {
  id: number;
  title: string;
  slug: string;
  full_path: string;
  sort_order: number;
  storage_key: string;
  folder_id?: number | null;
}

export interface TreeFolder {
  id: number;
  title: string;
  slug: string;
  full_path: string;
  sort_order: number;
  children: TreeFolder[];
  files: TreeFile[];
}

/**
 * Resolved node returned by /api/v1/nodes/resolve/{path}
 */
export interface ResolvedNode {
  id: number;
  title: string;
  slug: string;
  full_path: string;
  sort_order: number;
  parent_id?: number | null;
  folder_id?: number | null;
  file_path?: string | null;
  content?: string | null;
  content_type?: 'text' | 'base64' | null;
}

/**
 * Legacy TreeNode type — kept for backward compat in wiki sidebar etc.
 * Maps to the same shape the sidebar currently expects.
 */
export interface TreeNode {
  id: number;
  title: string;
  slug: string;
  full_path: string;
  node_type: 'FOLDER' | 'FILE';
  sort_order: number;
  children: TreeNode[];
}
