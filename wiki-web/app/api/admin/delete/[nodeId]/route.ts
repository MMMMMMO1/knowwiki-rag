import { NextRequest, NextResponse } from 'next/server';

const API_URL = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function DELETE(
    request: NextRequest,
    context: { params: Promise<{ nodeId: string }> }
) {
    try {
        const { nodeId } = await context.params;

        // 说明：从前端请求头读取数据库用户 JWT，并原样转发给后端校验。
        const authHeader = request.headers.get('Authorization');

        // 说明：删除接口需要同时知道节点类型和是否删除物理文件。
        const { searchParams } = new URL(request.url);
        const deletePhysical = searchParams.get('delete_physical') !== 'false';
        const itemType = searchParams.get('item_type') || 'file';

        // 说明：后端删除接口路径格式为 /delete/{item_type}/{item_id}。
        const url = `${API_URL}/api/v1/admin/delete/${itemType}/${nodeId}?delete_physical=${deletePhysical}`;
        const response = await fetch(url, {
            method: 'DELETE',
            headers: {
                'Authorization': authHeader || '',
            },
        });

        const data = await response.json();
        return NextResponse.json(data, { status: response.status });
    } catch {
        return NextResponse.json(
            { success: false, message: 'Delete failed' },
            { status: 500 }
        );
    }
}
