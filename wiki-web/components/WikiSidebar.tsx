'use client';

import { useCallback } from 'react';
import { Menu, Skeleton } from 'antd';
import type { MenuProps } from 'antd';
import { FileTextOutlined, FolderOutlined } from '@ant-design/icons';
import { TreeNode } from '@/types';
import { useRouter, usePathname } from 'next/navigation';

interface WikiSidebarProps {
    tree: TreeNode[];
    loading?: boolean;
}

type MenuItem = Required<MenuProps>['items'][number];

function buildMenuItems(nodes: TreeNode[]): MenuItem[] {
    return nodes
        .sort((a, b) => a.sort_order - b.sort_order)
        .map((node) => {
            if (node.node_type === 'FOLDER' && node.children?.length > 0) {
                return {
                    key: node.full_path,
                    icon: <FolderOutlined style={{ fontSize: 14 }} />,
                    label: node.title,
                    children: buildMenuItems(node.children),
                };
            }
            return {
                key: node.full_path,
                icon: node.node_type === 'FOLDER'
                    ? <FolderOutlined style={{ fontSize: 14 }} />
                    : <FileTextOutlined style={{ fontSize: 14 }} />,
                label: node.title,
            };
        });
}

function getDefaultOpenKeys(nodes: TreeNode[], targetPath: string): string[] {
    const keys: string[] = [];
    function traverse(items: TreeNode[]): boolean {
        for (const item of items) {
            if (item.full_path === targetPath) return true;
            if (item.children?.length) {
                if (traverse(item.children)) {
                    keys.push(item.full_path);
                    return true;
                }
            }
        }
        return false;
    }
    traverse(nodes);
    return keys;
}

export default function WikiSidebar({ tree, loading }: WikiSidebarProps) {
    const router = useRouter();
    const pathname = usePathname();

    // Extract current slug from path /wiki/...
    const currentKey = pathname.replace(/^\/wiki\/?/, '');

    const openKeys = getDefaultOpenKeys(tree, currentKey);
    const menuItems = buildMenuItems(tree);

    const handleSelect = useCallback(({ key }: { key: string }) => {
        router.push(`/wiki/${key}`);
    }, [router]);

    return (
        <aside
            style={{
                background: 'var(--color-sidebar)',
                height: '100%',
                overflowY: 'auto',
                overflowX: 'hidden',
                borderRight: 'none',
                padding: '8px 0 32px',
            }}
            className="no-scrollbar"
        >
            {/* 说明：目录组件只负责文件树，品牌区域由外层三栏布局统一控制。 */}
            {loading ? (
                <div style={{ padding: '0 16px' }}>
                    {[...Array(8)].map((_, i) => (
                        <Skeleton.Input
                            key={i}
                            active
                            size="small"
                            style={{ width: '100%', marginBottom: 8, borderRadius: 8 }}
                        />
                    ))}
                </div>
            ) : (
                <Menu
                    className="wiki-sidebar-menu"
                    mode="inline"
                    selectedKeys={[currentKey]}
                    defaultOpenKeys={openKeys}
                    items={menuItems}
                    onSelect={handleSelect}
                    style={{
                        background: 'transparent',
                        border: 'none',
                        fontFamily: 'var(--font-body)',
                    }}
                />
            )}
        </aside>
    );
}
