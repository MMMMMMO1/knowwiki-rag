import { buildAuthHeaders } from '@/lib/auth-token';

export type ChatConfig = {
    assistantName: string;
    greeting: string;
    placeholder: string;
    defaultMessages: string[];
    prompt?: string;
    model?: string;
    temperature?: string;
};

const LEARNING_RECOMMENDATION_PROMPT = `
请在正常回答用户问题后，额外给出学习推荐。学习推荐不需要来自知识库文档，可以基于用户问题本身自由推荐后续学习方向。

请严格把学习推荐放在回答末尾，并使用下面的机器可解析格式，不要使用 Markdown 代码块包裹：
<!--LEARNING_RECOMMENDATIONS_START-->
{"learningRecommendations":[{"title":"推荐学习主题","reason":"推荐原因，说明为什么下一步适合学这个","level":"入门|进阶|高级","keywords":["关键词1","关键词2"]}]}
<!--LEARNING_RECOMMENDATIONS_END-->

约束：
1. learningRecommendations 最多 3 条。
2. title、reason、level、keywords 必须使用中文。
3. keywords 每条最多 4 个。
4. 如果用户问题不适合推荐学习内容，返回 {"learningRecommendations":[]}。
`.trim();

export type ChatMessage = {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    sentAt?: number;
    sources?: unknown[];
    error?: string | boolean | null;
    errorMsg?: string | null;
    pending?: boolean;
};

type ChatHistoryItem = {
    role: 'user' | 'assistant' | string;
    content: string;
    sentAt?: number;
    sources?: unknown[];
    error?: string | boolean | null;
    errorMsg?: string | null;
};

export type StreamEvent = {
    uuid?: string;
    id?: string;
    type?: 'textResponseChunk' | 'textResponse' | 'abort' | string;
    textResponse?: string | null;
    sources?: unknown[];
    close?: boolean;
    error?: string | boolean | null;
    errorMsg?: string | null;
};

export function createChatConfig(): ChatConfig {
    return {
        assistantName: process.env.NEXT_PUBLIC_CHATBOT_ASSISTANT_NAME?.trim() || '智能学习助手',
        greeting: process.env.NEXT_PUBLIC_CHATBOT_GREETING?.trim() || '你好，我可以帮你查询当前知识库内容。',
        placeholder: process.env.NEXT_PUBLIC_CHATBOT_PLACEHOLDER?.trim() || '输入你的问题...',
        defaultMessages: parseDefaultMessages(
            process.env.NEXT_PUBLIC_CHATBOT_DEFAULT_MESSAGES?.trim()
            || '介绍一下这个知识库,我可以如何使用这个 Wiki'
        ),
        prompt: process.env.NEXT_PUBLIC_CHATBOT_PROMPT?.trim(),
        model: process.env.NEXT_PUBLIC_CHATBOT_MODEL?.trim(),
        temperature: process.env.NEXT_PUBLIC_CHATBOT_TEMPERATURE?.trim(),
    };
}

export function getOrCreateSessionId() {
    const storageKey = 'wiki_chat_session_id';
    const fallbackId = createId();

    try {
        const currentId = window.localStorage.getItem(storageKey);
        if (currentId) {
            return currentId;
        }

        window.localStorage.setItem(storageKey, fallbackId);
        return fallbackId;
    } catch {
        return fallbackId;
    }
}

export async function fetchChatHistory(
    sessionId: string
): Promise<ChatMessage[]> {
    const response = await fetch(`/api/chat/history?session_id=${sessionId}`, {
        headers: buildAuthHeaders(),
    });

    if (!response.ok) {
        throw new Error('历史消息加载失败');
    }

    const data = await response.json() as { history?: ChatHistoryItem[] };
    const history = Array.isArray(data.history) ? data.history : [];

    return history.map((message) => ({
        id: createId(),
        role: message.role === 'user' ? 'user' : 'assistant',
        content: message.content,
        sentAt: message.sentAt,
        sources: message.sources || [],
        error: message.error,
        errorMsg: message.errorMsg,
    }));
}

export async function resetChatSession(
    sessionId: string
) {
    const response = await fetch(`/api/chat/history?session_id=${sessionId}`, {
        method: 'DELETE',
        headers: buildAuthHeaders(),
    });

    return response.ok;
}

function parseDefaultMessages(value: string) {
    return value
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean);
}

function parseServerSentEvent(
    eventText: string,
    onEvent: (event: StreamEvent) => void
) {
    const data = eventText
        .split(/\r?\n/)
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.replace(/^data:\s?/, ''))
        .join('\n')
        .trim();

    if (!data || data === '[DONE]') {
        return;
    }

    try {
        onEvent(JSON.parse(data) as StreamEvent);
    } catch {
        // 说明：忽略无法解析的 SSE 片段，避免单个坏包中断已经收到的回复。
    }
}

async function emitServerError(
    response: Response,
    onEvent: (event: StreamEvent) => void
) {
    try {
        const serverResponse = await response.json() as StreamEvent;
        onEvent(serverResponse);
    } catch {
        onEvent({
            type: 'abort',
            textResponse: null,
            sources: [],
            close: true,
            error: `流式响应失败，状态码 ${response.status}`,
        });
    }
}

function createId() {
    if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
        return crypto.randomUUID();
    }

    // 说明：在非 HTTPS 的非安全上下文中，crypto.randomUUID 可能不可用。
    // 这里使用标准的 UUID v4 算法以兼容各种浏览器环境。
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        const v = c === 'x' ? r : (r & 0x3) | 0x8;
        return v.toString(16);
    });
}

// ── RAG 聊天 ─────────────────────────────────────────────

/**
 * 调用自研 RAG 后端的流式聊天接口。
 * SSE 格式为纯文本 token（data: 你好\n\n），通过包装 token 为 textResponseChunk 事件保持兼容。
 */
export async function streamRagChat(
    message: string,
    onEvent: (event: StreamEvent) => void,
    signal?: AbortSignal
) {
    const response = await fetch('/api/chat/rag/stream', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...buildAuthHeaders(),
        },
        body: JSON.stringify({ message }),
        signal,
    });

    if (!response.ok) {
        await emitServerError(response, onEvent);
        return;
    }

    if (!response.body) {
        onEvent({
            type: 'abort',
            textResponse: null,
            sources: [],
            close: true,
            error: '服务端没有返回可读取的流式响应',
        });
        return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split(/\n\n|\r\n\r\n/);
        buffer = events.pop() || '';

        for (const eventText of events) {
            const data = eventText
                .split(/\r?\n/)
                .filter((line) => line.startsWith('data:'))
                .map((line) => line.replace(/^data:\s?/, ''))
                .join('\n')
                .trim();

            if (!data) continue;
            if (data === '[DONE]') {
                // 结束事件：只标记完成，不覆盖已累积的答案（textResponse 必须为 null）
                onEvent({ type: 'textResponse', textResponse: null, sources: [], close: true, error: null });
                return;
            }
            if (data.startsWith('[ERROR]')) {
                onEvent({ type: 'abort', textResponse: null, sources: [], close: true, error: data });
                return;
            }

            // RAG 的 SSE 是纯文本 token，包装为 textResponseChunk 事件
            onEvent({
                type: 'textResponseChunk',
                textResponse: data,
                sources: [],
                close: false,
                error: null,
            });
        }
    }
}
