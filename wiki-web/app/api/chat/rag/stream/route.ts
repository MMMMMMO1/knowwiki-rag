import { NextRequest, NextResponse } from 'next/server';

const API_URL = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://wiki-backend:8000';

export async function POST(request: NextRequest) {
    try {
        const body = await request.json();
        const authHeader = request.headers.get('Authorization');

        const response = await fetch(`${API_URL}/api/v1/chat/rag/stream`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': authHeader || '',
            },
            body: JSON.stringify({ message: body.message }),
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({ detail: 'RAG 流式聊天失败' }));
            return NextResponse.json(errData, { status: response.status });
        }

        return new NextResponse(response.body, {
            headers: {
                'Content-Type': 'text/event-stream',
                'Cache-Control': 'no-cache, no-transform',
                'Connection': 'keep-alive',
            },
        });
    } catch (error) {
        console.error('RAG chat stream proxy failed:', error);
        return NextResponse.json(
            { detail: 'RAG 聊天连接失败' },
            { status: 500 }
        );
    }
}
