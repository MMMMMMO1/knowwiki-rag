import { NextRequest, NextResponse } from 'next/server';

const API_URL = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function GET(
    request: NextRequest,
    context: { params: Promise<{ path: string[] }> }
) {
    try {
        const { path } = await context.params;
        const authHeader = request.headers.get('Authorization');
        // 说明：逐段编码路径，既保留 Wiki 的层级结构，也避免文件名里的空格等字符破坏后端 URL。
        const encodedPath = path.map((segment) => encodeURIComponent(segment)).join('/');

        const response = await fetch(`${API_URL.replace(/\/$/, '')}/api/v1/nodes/resolve/${encodedPath}`, {
            cache: 'no-store',
            headers: {
                Authorization: authHeader || '',
            },
        });

        const data = await response.json();
        return NextResponse.json(data, {
            status: response.status,
            headers: {
                // 说明：文件内容可能在上传后立即访问，不能复用旧的解析结果。
                'Cache-Control': 'no-store',
            },
        });
    } catch (error) {
        console.error('Resolve node failed:', error);
        return NextResponse.json(
            { detail: 'Failed to resolve node' },
            { status: 500 }
        );
    }
}
