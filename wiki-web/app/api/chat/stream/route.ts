import { NextRequest, NextResponse } from 'next/server';

const API_URL = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function POST(request: NextRequest) {
    try {
        const body = await request.json();
        const authHeader = request.headers.get('Authorization');

        // Forward stream request to backend FastAPI
        const response = await fetch(`${API_URL}/api/v1/chat/stream`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': authHeader || '',
            },
            body: JSON.stringify(body),
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({ detail: 'Failed to stream chat' }));
            return NextResponse.json(errData, { status: response.status });
        }

        // Return the ReadableStream directly to client
        return new NextResponse(response.body, {
            headers: {
                'Content-Type': 'text/event-stream',
                'Cache-Control': 'no-cache, no-transform',
                'Connection': 'keep-alive',
            },
        });
    } catch (error) {
        console.error('Chat stream proxy failed:', error);
        return NextResponse.json(
            { detail: 'Chat stream connection error' },
            { status: 500 }
        );
    }
}
