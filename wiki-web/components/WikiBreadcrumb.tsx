'use client';

import { Breadcrumb } from 'antd';
import Link from 'next/link';
import { TreeNode } from '@/types';

interface WikiBreadcrumbProps {
    tree: TreeNode[];
    currentPath: string;
}

function findPath(nodes: TreeNode[], targetPath: string): TreeNode[] {
    for (const node of nodes) {
        if (node.full_path === targetPath) return [node];
        if (node.children?.length) {
            const childPath = findPath(node.children, targetPath);
            if (childPath.length) return [node, ...childPath];
        }
    }
    return [];
}

export default function WikiBreadcrumb({ tree, currentPath }: WikiBreadcrumbProps) {
    const pathNodes = findPath(tree, currentPath);

    const items = [
        {
            title: <Link href="/wiki">文档</Link>,
        },
        ...pathNodes.map((node, idx) => ({
            title: idx < pathNodes.length - 1
                ? <Link href={`/wiki/${node.full_path}`}>{node.title}</Link>
                : <span>{node.title}</span>,
        })),
    ];

    if (pathNodes.length === 0) return null;

    return (
        <Breadcrumb
            className="wiki-breadcrumb"
            items={items}
            style={{ fontSize: 11 }}
        />
    );
}
