import { NextRequest, NextResponse } from 'next/server';

const API_URL = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://wiki-backend:8000';

export async function POST(request: NextRequest) {
    try {
        const authHeader = request.headers.get('Authorization');
        const contentType = request.headers.get('Content-Type') || 'application/json';
        const body = await request.text();
        const response = await fetch(`${API_URL}/api/v1/rag/debug`, {
            method: 'POST',
            headers: {
                'Authorization': authHeader || '',
                'Content-Type': contentType,
            },
            body,
            signal: request.signal,
        });
        const data = await response.json();
        return NextResponse.json(data, { status: response.status });
    } catch (error) {
        console.error('RAG debug proxy failed:', error);
        return NextResponse.json({ success: false, detail: 'Connection error' }, { status: 500 });
    }
}
