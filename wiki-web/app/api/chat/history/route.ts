import { NextRequest, NextResponse } from 'next/server';

const API_URL = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function GET(request: NextRequest) {
    try {
        const { searchParams } = new URL(request.url);
        const sessionId = searchParams.get('session_id');
        const authHeader = request.headers.get('Authorization');

        if (!sessionId) {
            return NextResponse.json({ detail: 'session_id is required' }, { status: 400 });
        }

        const response = await fetch(`${API_URL}/api/v1/chat/history?session_id=${sessionId}`, {
            headers: {
                'Authorization': authHeader || '',
            },
        });

        const data = await response.json();
        return NextResponse.json(data, { status: response.status });
    } catch (error) {
        console.error('Fetch chat history failed:', error);
        return NextResponse.json({ detail: 'Failed to fetch chat history' }, { status: 500 });
    }
}

export async function DELETE(request: NextRequest) {
    try {
        const { searchParams } = new URL(request.url);
        const sessionId = searchParams.get('session_id');
        const authHeader = request.headers.get('Authorization');

        if (!sessionId) {
            return NextResponse.json({ detail: 'session_id is required' }, { status: 400 });
        }

        const response = await fetch(`${API_URL}/api/v1/chat/history?session_id=${sessionId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': authHeader || '',
            },
        });

        const data = await response.json();
        return NextResponse.json(data, { status: response.status });
    } catch (error) {
        console.error('Reset chat history failed:', error);
        return NextResponse.json({ detail: 'Failed to reset chat history' }, { status: 500 });
    }
}
