import { NextRequest, NextResponse } from 'next/server';

const API_URL = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://wiki-backend:8000';

export async function POST(
    request: NextRequest,
    context: { params: Promise<{ file_id: string }> }
) {
    try {
        const { file_id } = await context.params;
        const authHeader = request.headers.get('Authorization');
        const response = await fetch(`${API_URL}/api/v1/admin/knowledge/rebuild-file/${file_id}`, {
            method: 'POST',
            headers: { 'Authorization': authHeader || '' },
            signal: request.signal,
        });
        const data = await response.json();
        return NextResponse.json(data, { status: response.status });
    } catch (error) {
        console.error('Knowledge rebuild-file proxy failed:', error);
        return NextResponse.json({ success: false, detail: 'Connection error' }, { status: 500 });
    }
}
