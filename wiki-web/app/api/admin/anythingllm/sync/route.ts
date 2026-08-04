import { NextRequest, NextResponse } from 'next/server';

const API_URL = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function POST(request: NextRequest) {
    try {
        const authHeader = request.headers.get('Authorization');

        const response = await fetch(`${API_URL}/api/v1/admin/anythingllm/sync`, {
            method: 'POST',
            headers: {
                Authorization: authHeader || '',
            },
        });

        const data = await response.json();
        return NextResponse.json(data, { status: response.status });
    } catch {
        return NextResponse.json(
            { success: false, message: '触发 AnythingLLM 同步失败。' },
            { status: 500 }
        );
    }
}
