'use client';

import { useState, useCallback } from 'react';
import { Layout, Input, Switch, Tooltip } from 'antd';
import { SearchOutlined, ReadOutlined } from '@ant-design/icons';
import { TreeNode } from '@/types';
import Link from 'next/link';

const { Header } = Layout;

interface WikiHeaderProps {
    tree?: TreeNode[];
    isDark?: boolean;
    onThemeToggle?: () => void;
}

function flattenTree(nodes: TreeNode[]): TreeNode[] {
    const result: TreeNode[] = [];
    function traverse(items: TreeNode[]) {
        for (const item of items) {
            result.push(item);
            if (item.children?.length) traverse(item.children);
        }
    }
    traverse(nodes);
    return result;
}

export default function WikiHeader({ tree = [], isDark, onThemeToggle }: WikiHeaderProps) {
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
        const all = flattenTree(tree);
        const filtered = all.filter(
            (n) => n.node_type === 'FILE' && n.title.toLowerCase().includes(value.toLowerCase())
        ).slice(0, 8);
        setSearchResults(filtered);
        setShowDropdown(true);
    }, [tree]);

    return (
        <Header style={{
            background: 'var(--color-surface)',
            borderBottom: 'none',
            padding: '0 32px',
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            position: 'sticky',
            top: 0,
            zIndex: 100,
            gap: 24,
        }}>
            {/* Brand */}
            <Link href="/wiki" style={{ textDecoration: 'none', flexShrink: 0 }}>
                <span style={{
                    fontSize: 20,
                    fontWeight: 900,
                    fontFamily: 'var(--font-headline)',
                    color: 'var(--color-brand-text)',
                    letterSpacing: '-0.04em',
                }}>
                    智能学习助手
                </span>
            </Link>

            {/* Search */}
            <div style={{ flex: 1, maxWidth: 560, position: 'relative' }}>
                <Input
                    className="wiki-search"
                    prefix={<SearchOutlined style={{ color: 'var(--color-outline)', fontSize: 16 }} />}
                    placeholder="搜索文档..."
                    value={searchValue}
                    onChange={(e) => handleSearch(e.target.value)}
                    onBlur={() => setTimeout(() => setShowDropdown(false), 200)}
                    onFocus={() => searchValue && setShowDropdown(true)}
                    style={{
                        height: 44,
                        borderRadius: 12,
                        fontSize: 14,
                        fontFamily: 'var(--font-body)',
                    }}
                />
                {/* Search Dropdown */}
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
                                onClick={() => { setShowDropdown(false); setSearchValue(''); }}
                                style={{ textDecoration: 'none' }}
                            >
                                <div style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 10,
                                    padding: '10px 16px',
                                    cursor: 'pointer',
                                    transition: 'background 0.15s',
                                }}
                                    onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-surface-container)')}
                                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                                >
                                    <ReadOutlined style={{ color: 'var(--color-primary)', fontSize: 14 }} />
                                    <span style={{ fontSize: 13.5, color: 'var(--color-on-surface)', fontFamily: 'var(--font-body)' }}>
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

            {/* Actions */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 20, flexShrink: 0 }}>
                <Link href="/wiki" style={{ textDecoration: 'none' }}>
                    <span style={{
                        fontSize: 13,
                        fontWeight: 700,
                        fontFamily: 'var(--font-headline)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.04em',
                        color: 'var(--color-primary)',
                        paddingBottom: 2,
                    }}>
                        文档
                    </span>
                </Link>
                <Link href="/admin" style={{ textDecoration: 'none' }}>
                    <span style={{
                        fontSize: 13,
                        fontWeight: 600,
                        fontFamily: 'var(--font-headline)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.04em',
                        color: 'var(--color-outline)',
                        transition: 'color 0.2s',
                    }}
                        onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-primary)')}
                        onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-outline)')}
                    >
                        管理
                    </span>
                </Link>
                <div style={{ width: 1, height: 20, background: 'rgba(197,197,217,0.3)' }} />
                <Tooltip title={isDark ? '切换到亮色模式' : '切换到深色模式'}>
                    <Switch
                        checked={isDark}
                        onChange={onThemeToggle}
                        checkedChildren="🌙"
                        unCheckedChildren="☀️"
                        style={{ background: isDark ? 'var(--color-primary)' : undefined }}
                    />
                </Tooltip>
            </div>
        </Header>
    );
}
