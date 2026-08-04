'use client';

import { TreeNode } from '@/types';
import { RocketOutlined, BookOutlined, AppstoreOutlined, ThunderboltOutlined, ArrowRightOutlined } from '@ant-design/icons';
import Link from 'next/link';

interface WikiHomeBannerProps {
    tree: TreeNode[];
}

function getTopNodes(tree: TreeNode[]): TreeNode[] {
    // Get first 4 top-level or folder nodes for feature cards
    return tree.slice(0, 4);
}

const FEATURE_ICONS = [RocketOutlined, BookOutlined, AppstoreOutlined, ThunderboltOutlined];

export default function WikiHomeBanner({ tree }: WikiHomeBannerProps) {
    const featuredNodes = getTopNodes(tree);

    return (
        <div className="animate-fade-in-up">
            {/* Hero Banner */}
            <section style={{
                position: 'relative',
                overflow: 'hidden',
                borderRadius: 8,
                marginBottom: 48,
                aspectRatio: '21/9',
                minHeight: 240,
                display: 'flex',
                alignItems: 'center',
                padding: '48px 56px',
                background: 'var(--color-inverse-surface)',
            }}>
                {/* Content */}
                <div style={{ position: 'relative', zIndex: 10, maxWidth: 600 }}>
                    <span style={{
                        display: 'inline-block',
                        padding: '4px 14px',
                        background: 'rgba(250,249,245,0.12)',
                        backdropFilter: 'blur(8px)',
                        borderRadius: 999,
                        color: 'var(--color-primary-container)',
                        fontSize: 10,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: 0,
                        marginBottom: 20,
                        fontFamily: 'var(--font-headline)',
                    }}>
                        内部知识库
                    </span>
                    <h1 style={{
                        fontSize: 'clamp(2rem, 4vw, 3.5rem)',
                        fontWeight: 800,
                        color: '#ffffff',
                        fontFamily: 'var(--font-headline)',
                        margin: '0 0 16px',
                        letterSpacing: 0,
                        lineHeight: 1.15,
                    }}>
                        欢迎使用智能学习助手
                    </h1>
                    <p style={{
                        color: 'rgba(255,255,255,0.82)',
                        fontSize: 16,
                        maxWidth: 460,
                        lineHeight: 1.7,
                        margin: 0,
                        fontFamily: 'var(--font-body)',
                    }}>
                        统一的知识管理平台，汇集所有技术文档、工程规范和项目资料。
                    </p>
                </div>
            </section>

            {/* Feature Grid */}
            {featuredNodes.length > 0 && (
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
                    gap: 24,
                    marginBottom: 48,
                }}>
                    {featuredNodes.map((node, idx) => {
                        const Icon = FEATURE_ICONS[idx % FEATURE_ICONS.length];
                        const isFirst = idx === 0;
                        return (
                            <Link
                                key={node.id}
                                href={`/wiki/${node.full_path}`}
                                style={{ textDecoration: 'none' }}
                            >
                                <div style={{
                                    background: isFirst ? 'var(--color-inverse-surface)' : 'var(--color-surface-container-lowest)',
                                    borderRadius: 8,
                                    padding: '28px 32px',
                                    height: '100%',
                                    boxShadow: 'var(--shadow-sm)',
                                    border: isFirst ? 'none' : '1px solid var(--color-outline-variant)',
                                    cursor: 'pointer',
                                    transition: 'transform 0.2s, box-shadow 0.2s',
                                }}
                                    onMouseEnter={(e) => {
                                        (e.currentTarget as HTMLDivElement).style.transform = 'translateY(-3px)';
                                        (e.currentTarget as HTMLDivElement).style.boxShadow = 'var(--shadow-md)';
                                    }}
                                    onMouseLeave={(e) => {
                                        (e.currentTarget as HTMLDivElement).style.transform = 'translateY(0)';
                                        (e.currentTarget as HTMLDivElement).style.boxShadow = 'var(--shadow-sm)';
                                    }}
                                >
                                    <div style={{
                                        width: 44,
                                        height: 44,
                                        borderRadius: 8,
                                        background: isFirst ? 'rgba(255,255,255,0.12)' : 'var(--color-surface-container)',
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                        marginBottom: 18,
                                    }}>
                                        <Icon style={{
                                            fontSize: 20,
                                            color: isFirst ? '#ffffff' : 'var(--color-primary)',
                                        }} />
                                    </div>
                                    <h3 style={{
                                        fontSize: 17,
                                        fontWeight: 700,
                                        fontFamily: 'var(--font-headline)',
                                        color: isFirst ? '#ffffff' : 'var(--color-on-surface)',
                                        margin: '0 0 10px',
                                        letterSpacing: 0,
                                    }}>
                                        {node.title}
                                    </h3>
                                    <p style={{
                                        fontSize: 13,
                                        color: isFirst ? 'rgba(255,255,255,0.65)' : 'var(--color-on-surface-variant)',
                                        margin: '0 0 20px',
                                        lineHeight: 1.6,
                                        fontFamily: 'var(--font-body)',
                                    }}>
                                        {node.node_type === 'FOLDER'
                                            ? `${node.children?.length || 0} 篇文档`
                                            : '点击查看文档'}
                                    </p>
                                    <span style={{
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: 6,
                                        fontSize: 13,
                                        fontWeight: 700,
                                        color: isFirst ? 'var(--color-primary-container)' : 'var(--color-primary)',
                                        fontFamily: 'var(--font-headline)',
                                    }}>
                                        查看 <ArrowRightOutlined style={{ fontSize: 12 }} />
                                    </span>
                                </div>
                            </Link>
                        );
                    })}
                </div>
            )}

            {/* Quick Stats */}
            <div style={{
                background: 'var(--color-surface-container-lowest)',
                borderRadius: 8,
                padding: '28px 36px',
                display: 'flex',
                gap: 48,
                flexWrap: 'wrap',
                border: '1px solid var(--color-outline-variant)',
                boxShadow: 'var(--shadow-sm)',
            }}>
                <div>
                    <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--color-primary)', fontFamily: 'var(--font-headline)' }}>
                        {tree.length}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--color-outline)', fontFamily: 'var(--font-body)', marginTop: 2 }}>
                        顶层目录
                    </div>
                </div>
                <div style={{ width: 1, background: 'var(--color-outline-variant)', alignSelf: 'stretch' }} />
                <div>
                    <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--color-primary)', fontFamily: 'var(--font-headline)' }}>
                        {tree.reduce((acc, n) => acc + (n.children?.length || 0), 0)}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--color-outline)', fontFamily: 'var(--font-body)', marginTop: 2 }}>
                        子文档
                    </div>
                </div>
                <div style={{ width: 1, background: 'var(--color-outline-variant)', alignSelf: 'stretch' }} />
                <div>
                    <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--color-primary)', fontFamily: 'var(--font-headline)' }}>
                        实时
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--color-outline)', fontFamily: 'var(--font-body)', marginTop: 2 }}>
                        自动同步
                    </div>
                </div>
            </div>
        </div>
    );
}
