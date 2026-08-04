import { TreeNode, ResolvedNode, TreeFolder, TreeFile } from '@/types';
import { buildAuthHeaders, handleUnauthorizedResponse } from '@/lib/auth-token';

function adaptTree(items: (TreeFolder | TreeFile)[]): TreeNode[] {
    const result: TreeNode[] = [];
    const sortedItems = [...items].sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0));

    for (const item of sortedItems) {
        if ('files' in item || 'children' in item) {
            const folderItem = item as TreeFolder;
            // Folder mapping
            const folderChildren = adaptTree(folderItem.children || []);
            const fileChildren = (folderItem.files || []).map((f: TreeFile) => ({
                id: f.id,
                title: f.title,
                slug: f.slug,
                full_path: f.full_path,
                node_type: 'FILE' as const,
                sort_order: f.sort_order || 0,
                children: [],
            }));

            result.push({
                id: folderItem.id,
                title: folderItem.title,
                slug: folderItem.slug,
                full_path: folderItem.full_path,
                node_type: 'FOLDER' as const,
                sort_order: folderItem.sort_order || 0,
                children: [...folderChildren, ...fileChildren].sort((a, b) => a.sort_order - b.sort_order),
            });
        } else {
            const fileItem = item as TreeFile;
            // File mapping
            result.push({
                id: fileItem.id,
                title: fileItem.title,
                slug: fileItem.slug,
                full_path: fileItem.full_path,
                node_type: 'FILE' as const,
                sort_order: fileItem.sort_order || 0,
                children: [],
            });
        }
    }
    return result;
}

export async function getTree(): Promise<TreeNode[]> {
    // 说明：客户端统一访问本地 Next.js API，由服务端代理决定真实后端地址，避免部署环境暴露内部服务名。
    const res = await fetch('/api/nodes/tree', {
        cache: 'no-store',
        headers: buildAuthHeaders(),
    });
    if (handleUnauthorizedResponse(res)) {
        throw new Error('登录已过期，请重新登录');
    }
    if (!res.ok) {
        throw new Error('Failed to fetch tree');
    }
    const rawData = await res.json();
    return adaptTree(rawData);
}

export async function resolveNode(path: string): Promise<ResolvedNode> {
    // 说明：按路径段编码，避免中文、空格或特殊字符在代理 URL 中被错误解析。
    const encodedPath = path
        .split('/')
        .filter(Boolean)
        .map((segment) => encodeURIComponent(segment))
        .join('/');
    const res = await fetch(`/api/nodes/resolve/${encodedPath}`, {
        cache: 'no-store',
        headers: buildAuthHeaders(),
    });
    if (handleUnauthorizedResponse(res)) {
        throw new Error('登录已过期，请重新登录');
    }
    if (!res.ok) {
        throw new Error('Failed to resolve node');
    }
    return res.json();
}
