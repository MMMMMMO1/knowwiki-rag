import { buildAuthHeaders } from '@/lib/auth-token';

export type AnythingLLMChatConfig = {
    embedId: string;
    username?: string;
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

export type AnythingLLMChatMessage = {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    sentAt?: number;
    sources?: unknown[];
    error?: string | boolean | null;
    errorMsg?: string | null;
    pending?: boolean;
};

type AnythingLLMHistoryItem = {
    role: 'user' | 'assistant' | string;
    content: string;
    sentAt?: number;
    sources?: unknown[];
    error?: string | boolean | null;
    errorMsg?: string | null;
};

export type AnythingLLMStreamEvent = {
    uuid?: string;
    id?: string;
    type?: 'textResponseChunk' | 'textResponse' | 'abort' | string;
    textResponse?: string | null;
    sources?: unknown[];
    close?: boolean;
    error?: string | boolean | null;
    errorMsg?: string | null;
};

export function createAnythingLLMChatConfig(): AnythingLLMChatConfig | null {
    const embedId = process.env.NEXT_PUBLIC_CHATBOT_EMBED_ID?.trim();

    if (!embedId) {
        return null;
    }

    return {
        embedId,
        username: process.env.NEXT_PUBLIC_CHATBOT_USERNAME?.trim(),
        assistantName: process.env.NEXT_PUBLIC_CHATBOT_ASSISTANT_NAME?.trim() || '智能学习助手',
        greeting: process.env.NEXT_PUBLIC_CHATBOT_GREETING?.trim() || '你好，我可以帮你查询当前知识库内容。',
        placeholder: process.env.NEXT_PUBLIC_CHATBOT_PLACEHOLDER?.trim() || '输入你的问题...',
        defaultMessages: parseDefaultMessages(
            process.env.NEXT_PUBLIC_CHATBOT_DEFAULT_MESSAGES?.trim()
            || '介绍一下这个知识库,我可以如何使用这个 Wiki'
        ),
        prompt: buildChatPrompt(process.env.NEXT_PUBLIC_CHATBOT_PROMPT?.trim()),
        model: process.env.NEXT_PUBLIC_CHATBOT_MODEL?.trim(),
        temperature: process.env.NEXT_PUBLIC_CHATBOT_TEMPERATURE?.trim(),
    };
}

export function getOrCreateAnythingLLMSessionId(embedId: string) {
    const storageKey = `allm_${embedId}_session_id`;
    const fallbackId = createId();

    try {
        const currentId = window.localStorage.getItem(storageKey);
        if (currentId) {
            return currentId;
        }

        window.localStorage.setItem(storageKey, fallbackId);
        return fallbackId;
    } catch {
        // 说明：隐私模式或禁用 localStorage 时仍允许当前页面完成一次会话。
        return fallbackId;
    }
}

export async function fetchAnythingLLMHistory(
    sessionId: string
): Promise<AnythingLLMChatMessage[]> {
    const response = await fetch(`/api/chat/history?session_id=${sessionId}`, {
        headers: buildAuthHeaders(),
    });

    if (!response.ok) {
        throw new Error('历史消息加载失败');
    }

    const data = await response.json() as { history?: AnythingLLMHistoryItem[] };
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

export async function resetAnythingLLMSession(
    sessionId: string
) {
    const response = await fetch(`/api/chat/history?session_id=${sessionId}`, {
        method: 'DELETE',
        headers: buildAuthHeaders(),
    });

    return response.ok;
}

export async function streamAnythingLLMChat(
    config: AnythingLLMChatConfig,
    sessionId: string,
    message: string,
    onEvent: (event: AnythingLLMStreamEvent) => void,
    signal?: AbortSignal
) {
    const response = await fetch(`/api/chat/stream`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...buildAuthHeaders(),
        },
        body: JSON.stringify({
            message,
            session_id: sessionId,
            prompt: config.prompt || null,
            model: config.model || null,
            temperature: config.temperature ? parseFloat(config.temperature) : null,
        }),
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

    // 说明：AnythingLLM 使用标准 SSE 文本流，这里只解析 data 行并保持事件顺序。
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { value, done } = await reader.read();
        if (done) {
            break;
        }

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split(/\n\n|\r\n\r\n/);
        buffer = events.pop() || '';

        for (const eventText of events) {
            parseServerSentEvent(eventText, onEvent);
        }
    }

    if (buffer.trim()) {
        parseServerSentEvent(buffer, onEvent);
    }
}

function parseDefaultMessages(value: string) {
    return value
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean);
}

function buildChatPrompt(prompt?: string) {
    if (!prompt) {
        return LEARNING_RECOMMENDATION_PROMPT;
    }

    // 说明：保留用户已有的 AnythingLLM prompt，只在末尾追加学习推荐输出协议。
    return `${prompt}\n\n${LEARNING_RECOMMENDATION_PROMPT}`;
}

function parseServerSentEvent(
    eventText: string,
    onEvent: (event: AnythingLLMStreamEvent) => void
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
        onEvent(JSON.parse(data) as AnythingLLMStreamEvent);
    } catch {
        // 说明：忽略无法解析的 SSE 片段，避免单个坏包中断已经收到的回复。
    }
}

async function emitServerError(
    response: Response,
    onEvent: (event: AnythingLLMStreamEvent) => void
) {
    try {
        const serverResponse = await response.json() as AnythingLLMStreamEvent;
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
    // 这里使用标准的 UUID v4 算法以保证 AnythingLLM 会话校验能通过（它要求必须是合法的 UUID）。
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        const v = c === 'x' ? r : (r & 0x3) | 0x8;
        return v.toString(16);
    });
}

// ── RAG 聊天 ─────────────────────────────────────────────

/**
 * 调用自研 RAG 后端的流式聊天接口。
 *
 * 与 streamAnythingLLMChat 的差异：
 * 1. 请求体只需要 {message}，不需要 session_id / prompt / model / temperature
 * 2. SSE 格式为纯文本 token（data: 你好\n\n），而非 JSON 事件
 * 3. 通过包装 token 为 textResponseChunk 事件，保持 WikiChatPanel 兼容
 */
export async function streamRagChat(
    message: string,
    onEvent: (event: AnythingLLMStreamEvent) => void,
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
                onEvent({ type: 'textResponse', textResponse: '', sources: [], close: true, error: null });
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
