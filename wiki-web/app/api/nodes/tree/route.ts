import { NextRequest, NextResponse } from 'next/server';

const API_URL = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function GET(request: NextRequest) {
    try {
        const authHeader = request.headers.get('Authorization');
        // 说明：节点树必须走 Next.js 服务端代理，避免浏览器端依赖固定的 Docker 内部服务名。
        const response = await fetch(`${API_URL.replace(/\/$/, '')}/api/v1/nodes/tree`, {
            cache: 'no-store',
            headers: {
                Authorization: authHeader || '',
            },
        });

        const data = await response.json();
        return NextResponse.json(data, {
            status: response.status,
            headers: {
                // 说明：上传、删除、新建文件夹后需要立即看到最新目录，禁止中间层缓存旧树。
                'Cache-Control': 'no-store',
            },
        });
    } catch (error) {
        console.error('Fetch nodes tree failed:', error);
        return NextResponse.json(
            { detail: 'Failed to fetch tree' },
            { status: 500 }
        );
    }
}
