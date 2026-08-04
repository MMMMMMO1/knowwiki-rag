import { NextRequest, NextResponse } from 'next/server';

const API_URL = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function POST(request: NextRequest) {
    try {
        const authHeader = request.headers.get('Authorization');
        const payload = await request.json();

        // 说明：新建文件夹也走服务端代理，保证管理端目录写入和目录刷新使用同一个后端地址来源。
        const response = await fetch(`${API_URL.replace(/\/$/, '')}/api/v1/admin/folder`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': authHeader || '',
            },
            body: JSON.stringify(payload),
        });

        const data = await response.json();
        return NextResponse.json(data, { status: response.status });
    } catch (error) {
        console.error('Create folder failed:', error);
        return NextResponse.json(
            { detail: '创建文件夹失败' },
            { status: 500 }
        );
    }
}
