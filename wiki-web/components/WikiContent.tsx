'use client';

import { Skeleton, Empty } from 'antd';
import { ResolvedNode } from '@/types';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import 'highlight.js/styles/github-dark-dimmed.css';
import dynamic from 'next/dynamic';

const PDFViewerWrapper = dynamic(() => import('./WikiPDFViewer'), { ssr: false });

interface WikiContentProps {
    node: ResolvedNode | null;
    loading?: boolean;
}

function isPDF(node: ResolvedNode) {
    return node.file_path?.toLowerCase().endsWith('.pdf') || node.content_type === 'base64';
}

export default function WikiContent({ node, loading }: WikiContentProps) {
    if (loading) {
        return (
            <div style={{ padding: '0 0 48px' }}>
                <Skeleton active paragraph={{ rows: 3 }} style={{ marginBottom: 32 }} />
                <Skeleton active paragraph={{ rows: 8 }} />
            </div>
        );
    }

    if (!node) {
        return (
            <Empty
                description="未找到该文档"
                style={{ marginTop: 80 }}
            />
        );
    }

    if (isPDF(node)) {
        return (
            <div style={{ width: '100%', height: 'calc(100vh - 180px)', minHeight: 600 }}>
                <PDFViewerWrapper base64={node.content ?? ''} />
            </div>
        );
    }

    return (
        <article className="wiki-markdown animate-fade-in-up">
            <ReactMarkdown rehypePlugins={[rehypeHighlight]}>
                {node.content}
            </ReactMarkdown>
        </article>
    );
}
