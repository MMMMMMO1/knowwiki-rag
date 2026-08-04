'use client';

import { useCallback, useState } from 'react';
import { Input } from 'antd';
import { ReadOutlined, SearchOutlined } from '@ant-design/icons';
import Link from 'next/link';
import { TreeNode } from '@/types';

type WikiSearchBarProps = {
    tree?: TreeNode[];
};

function flattenTree(nodes: TreeNode[]) {
    const result: TreeNode[] = [];

    function traverse(items: TreeNode[]) {
        for (const item of items) {
            result.push(item);
            if (item.children?.length) {
                traverse(item.children);
            }
        }
    }

    traverse(nodes);
    return result;
}

export default function WikiSearchBar({ tree = [] }: WikiSearchBarProps) {
    const [searchValue, setSearchValue] = useState('');
    const [searchResults, setSearchResults] = useState<TreeNode[]>([]);
    const [showDropdown, setShowDropdown] = useState(false);

    const handleSearch = useCallback((value: string) => {
        setSearchValue(value);

        if (!value.trim()) {
            setSearchResults([]);
            setShowDropdown(false);
            return;
        }

        // 说明：沿用原顶栏搜索逻辑，只搜索文件节点标题，避免目录命中后无法解析正文。
        const allNodes = flattenTree(tree);
        const filtered = allNodes
            .filter((node) => (
                node.node_type === 'FILE'
                && node.title.toLowerCase().includes(value.toLowerCase())
            ))
            .slice(0, 8);

        setSearchResults(filtered);
        setShowDropdown(true);
    }, [tree]);

    return (
        <div style={{ position: 'relative', width: '100%' }}>
            <Input
                className="wiki-search"
                prefix={<SearchOutlined style={{ color: 'var(--color-outline)', fontSize: 16 }} />}
                placeholder="搜索文档..."
                value={searchValue}
                onChange={(event) => handleSearch(event.target.value)}
                onBlur={() => setTimeout(() => setShowDropdown(false), 200)}
                onFocus={() => searchValue && setShowDropdown(true)}
                style={{
                    height: 44,
                    borderRadius: 12,
                    fontSize: 14,
                    fontFamily: 'var(--font-body)',
                }}
            />

            {showDropdown && searchResults.length > 0 && (
                <div style={{
                    position: 'absolute',
                    top: 'calc(100% + 8px)',
                    left: 0,
                    right: 0,
                    background: 'var(--color-surface-container-lowest)',
                    borderRadius: 14,
                    boxShadow: '0 8px 32px rgba(0,0,0,0.12)',
                    border: '1px solid var(--color-outline-variant)',
                    zIndex: 200,
                    overflow: 'hidden',
                }}>
                    {searchResults.map((node) => (
                        <Link
                            key={node.id}
                            href={`/wiki/${node.full_path}`}
                            onClick={() => {
                                setShowDropdown(false);
                                setSearchValue('');
                            }}
                            style={{ textDecoration: 'none' }}
                        >
                            <div
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 10,
                                    padding: '10px 16px',
                                    cursor: 'pointer',
                                    transition: 'background 0.15s',
                                }}
                                onMouseEnter={(event) => {
                                    event.currentTarget.style.background = 'var(--color-surface-container)';
                                }}
                                onMouseLeave={(event) => {
                                    event.currentTarget.style.background = 'transparent';
                                }}
                            >
                                <ReadOutlined style={{ color: 'var(--color-primary)', fontSize: 14 }} />
                                <span style={{
                                    fontSize: 13.5,
                                    color: 'var(--color-on-surface)',
                                    fontFamily: 'var(--font-body)',
                                }}>
                                    {node.title}
                                </span>
                            </div>
                        </Link>
                    ))}
                </div>
            )}

            {showDropdown && searchResults.length === 0 && searchValue && (
                <div style={{
                    position: 'absolute',
                    top: 'calc(100% + 8px)',
                    left: 0,
                    right: 0,
                    background: 'var(--color-surface-container-lowest)',
                    borderRadius: 14,
                    boxShadow: '0 8px 32px rgba(0,0,0,0.12)',
                    padding: '16px',
                    textAlign: 'center',
                    color: 'var(--color-outline)',
                    fontSize: 13,
                    fontFamily: 'var(--font-body)',
                    zIndex: 200,
                }}>
                    未找到相关文档
                </div>
            )}
        </div>
    );
}
