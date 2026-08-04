import { NextRequest, NextResponse } from 'next/server';

const API_URL = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function GET(request: NextRequest) {
    try {
        const authHeader = request.headers.get('Authorization');

        const response = await fetch(`${API_URL}/api/v1/admin/users`, {
            method: 'GET',
            headers: {
                Authorization: authHeader || '',
            },
        });

        const data = await response.json();
        return NextResponse.json(data, { status: response.status });
    } catch (error) {
        console.error('List users failed:', error);
        return NextResponse.json({ detail: 'Failed to list users' }, { status: 500 });
    }
}

export async function POST(request: NextRequest) {
    try {
        const authHeader = request.headers.get('Authorization');
        const body = await request.json();

        const response = await fetch(`${API_URL}/api/v1/admin/users`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: authHeader || '',
            },
            body: JSON.stringify(body),
        });

        const data = await response.json();
        return NextResponse.json(data, { status: response.status });
    } catch (error) {
        console.error('Create user failed:', error);
        return NextResponse.json({ detail: 'Failed to create user' }, { status: 500 });
    }
}
