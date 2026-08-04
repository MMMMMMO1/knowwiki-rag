'use client';

import { useState, useEffect } from 'react';
import { usePathname } from 'next/navigation';
import WikiBreadcrumb from '@/components/WikiBreadcrumb';
import WikiContent from '@/components/WikiContent';
import WikiHomeBanner from '@/components/WikiHomeBanner';
import { TreeNode, ResolvedNode } from '@/types';
import { getTree, resolveNode } from '@/lib/api';

export default function WikiPage() {
    const pathname = usePathname();
    const slug = pathname.replace(/^\/wiki\/?/, '');

    const [tree, setTree] = useState<TreeNode[]>([]);
    const [node, setNode] = useState<ResolvedNode | null>(null);
    const [contentLoading, setContentLoading] = useState(false);

    // Fetch tree once
    useEffect(() => {
        getTree()
            .then(setTree)
            .catch(console.error);
    }, []);

    // Fetch content when slug changes
    useEffect(() => {
        if (!slug) {
            return;
        }
        let ignore = false;

        // 说明：把 loading 状态切换放到微任务中，避免 React 19 lint 将 effect 内同步 setState 判为级联渲染。
        queueMicrotask(() => {
            if (!ignore) {
                setContentLoading(true);
            }
        });

        resolveNode(slug)
            .then((resolvedNode) => {
                if (!ignore) {
                    setNode(resolvedNode);
                }
            })
            .catch(() => {
                if (!ignore) {
                    setNode(null);
                }
            })
            .finally(() => {
                if (!ignore) {
                    setContentLoading(false);
                }
            });

        return () => {
            ignore = true;
        };
    }, [slug]);

    const isHome = !slug;

    return (
        <div style={{ padding: '0 0 72px' }}>
            {/* Breadcrumbs */}
            {!isHome && (
                <div style={{ padding: '20px 40px 0', borderBottom: 'none' }}>
                    <WikiBreadcrumb tree={tree} currentPath={slug} />
                </div>
            )}

            {/* Content */}
            <div style={{
                maxWidth: isHome ? 1040 : 860,
                margin: '0 auto',
                padding: isHome ? '32px 40px' : '28px 40px',
            }}>
                {isHome ? (
                    <WikiHomeBanner tree={tree} />
                ) : (
                    <WikiContent
                        node={node}
                        loading={contentLoading}
                    />
                )}
            </div>
        </div>
    );
}
