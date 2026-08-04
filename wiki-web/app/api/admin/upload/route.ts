import { NextRequest, NextResponse } from 'next/server';

const WIKI_API_URL = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function getTextField(formData: FormData, fieldName: string): string {
    const value = formData.get(fieldName);
    return typeof value === 'string' ? value.trim() : '';
}

async function readResponseBody(response: Response): Promise<unknown> {
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
        return response.json();
    }

    return { message: await response.text() };
}

export async function POST(request: NextRequest) {
    try {
        const authHeader = request.headers.get('Authorization');

        let formData: FormData;
        try {
            formData = await request.formData();
        } catch {
            return NextResponse.json(
                { success: false, message: '请使用 multipart/form-data 格式上传文件。' },
                { status: 400 }
            );
        }

        const uploadFile = formData.get('file');
        if (!(uploadFile instanceof File)) {
            return NextResponse.json(
                { success: false, message: '请求中缺少 file 文件字段。' },
                { status: 400 }
            );
        }

        const wikiFormData = new FormData();
        // Next.js 代理只把文件和 Wiki 目录信息传给后端；AnythingLLM 同步由后端异步处理。
        wikiFormData.append('file', uploadFile, uploadFile.name);

        const folderId = getTextField(formData, 'folder_id');
        if (folderId) {
            wikiFormData.append('folder_id', folderId);
        }

        const wikiResponse = await fetch(`${WIKI_API_URL.replace(/\/$/, '')}/api/v1/admin/upload`, {
            method: 'POST',
            headers: {
                Authorization: authHeader || '',
            },
            body: wikiFormData,
        });

        const wikiData = await readResponseBody(wikiResponse);
        return NextResponse.json(wikiData, { status: wikiResponse.status });
    } catch (error) {
        console.error('Wiki upload proxy failed:', error);
        return NextResponse.json(
            { success: false, message: '上传文件失败。' },
            { status: 500 }
        );
    }
}
