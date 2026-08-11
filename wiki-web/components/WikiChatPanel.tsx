'use client';

import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Empty, Input, Spin, Tooltip } from 'antd';
import { BulbOutlined, DeleteOutlined, ReloadOutlined, SendOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import {
    AnythingLLMChatMessage,
    AnythingLLMStreamEvent,
    createAnythingLLMChatConfig,
    fetchAnythingLLMHistory,
    getOrCreateAnythingLLMSessionId,
    resetAnythingLLMSession,
    streamAnythingLLMChat,
    streamRagChat,
} from '@/lib/anythingllm-chat';

const { TextArea } = Input;

type LearningRecommendation = {
    title: string;
    reason: string;
    level?: string;
    keywords: string[];
};

export default function WikiChatPanel() {
    const config = useMemo(() => createAnythingLLMChatConfig(), []);
    const [sessionId, setSessionId] = useState('');
    const [messages, setMessages] = useState<AnythingLLMChatMessage[]>([]);
    const [inputValue, setInputValue] = useState('');
    const [loadingHistory, setLoadingHistory] = useState(false);
    const [sending, setSending] = useState(false);
    const [error, setError] = useState('');
    const scrollRef = useRef<HTMLDivElement | null>(null);

    useEffect(() => {
        if (!config) {
            return;
        }

        setSessionId(getOrCreateAnythingLLMSessionId(config.embedId));
    }, [config]);

    useEffect(() => {
        if (!config || !sessionId) {
            return;
        }

        let ignore = false;

        async function loadHistory() {
            setLoadingHistory(true);
            setError('');

            try {
                const history = await fetchAnythingLLMHistory(sessionId);
                if (!ignore) {
                    setMessages(history);
                }
            } catch (historyError) {
                if (!ignore) {
                    setError(historyError instanceof Error ? historyError.message : '历史消息加载失败');
                }
            } finally {
                if (!ignore) {
                    setLoadingHistory(false);
                }
            }
        }

        loadHistory();

        return () => {
            ignore = true;
        };
    }, [config, sessionId]);

    useEffect(() => {
        // 说明：每次消息变化都滚到底部，保证流式回复追加时用户能看到最新内容。
        scrollRef.current?.scrollTo({
            top: scrollRef.current.scrollHeight,
            behavior: 'smooth',
        });
    }, [messages]);

    const handleSubmit = async (event?: FormEvent, suggestedMessage?: string) => {
        event?.preventDefault();

        if (!config || !sessionId || sending) {
            return;
        }

        const message = (suggestedMessage || inputValue).trim();
        if (!message) {
            return;
        }

        const userMessage: AnythingLLMChatMessage = {
            id: createLocalId(),
            role: 'user',
            content: message,
            sentAt: Math.floor(Date.now() / 1000),
        };
        const assistantMessage: AnythingLLMChatMessage = {
            id: createLocalId(),
            role: 'assistant',
            content: '',
            sentAt: Math.floor(Date.now() / 1000),
            sources: [],
            pending: true,
        };

        setMessages((current) => [...current, userMessage, assistantMessage]);
        setInputValue('');
        setSending(true);
        setError('');

        try {
            await streamRagChat(
                message,
                (streamEvent) => {
                    applyStreamEvent(streamEvent, assistantMessage.id);
                }
            );
        } catch (streamError) {
            setMessages((current) => current.map((item) => (
                item.id === assistantMessage.id
                    ? {
                        ...item,
                        pending: false,
                        error: true,
                        errorMsg: streamError instanceof Error ? streamError.message : '消息发送失败',
                    }
                    : item
            )));
        } finally {
            setSending(false);
        }
    };

    const handleReset = async () => {
        if (!config || !sessionId || sending) {
            return;
        }

        setError('');
        const ok = await resetAnythingLLMSession(sessionId);

        if (ok) {
            setMessages([]);
            return;
        }

        setError('会话重置失败，请稍后重试');
    };

    const applyStreamEvent = (streamEvent: AnythingLLMStreamEvent, assistantId: string) => {
        setMessages((current) => current.map((item) => {
            if (item.id !== assistantId) {
                return item;
            }

            if (streamEvent.type === 'abort') {
                return {
                    ...item,
                    pending: false,
                    error: streamEvent.error || true,
                    errorMsg: streamEvent.errorMsg || String(streamEvent.error || '服务端中止了回复'),
                    sources: streamEvent.sources || item.sources,
                };
            }

            if (streamEvent.type === 'textResponseChunk') {
                return {
                    ...item,
                    content: `${item.content}${streamEvent.textResponse || ''}`,
                    pending: !streamEvent.close,
                    sources: streamEvent.sources || item.sources,
                    error: streamEvent.error,
                    errorMsg: streamEvent.errorMsg,
                };
            }

            if (streamEvent.type === 'textResponse') {
                return {
                    ...item,
                    content: streamEvent.textResponse ?? item.content,
                    pending: false,
                    sources: streamEvent.sources || item.sources,
                    error: streamEvent.error,
                    errorMsg: streamEvent.errorMsg,
                };
            }

            return item;
        }));
    };

    if (!config) {
        return (
            <aside className="wiki-chat-panel">
                <div className="wiki-chat-panel__header">
                    <div>
                        <div className="wiki-chat-panel__eyebrow">AI Assistant</div>
                        <h2>智能问答</h2>
                    </div>
                </div>
                <Empty description="AI 助手未配置" />
            </aside>
        );
    }

    return (
        <aside className="wiki-chat-panel">
            <div className="wiki-chat-panel__header">
                <div>
                    <div className="wiki-chat-panel__eyebrow">AI Assistant</div>
                    <h2>{config.assistantName}</h2>
                </div>
                <div className="wiki-chat-panel__actions">
                    <Tooltip title="重新加载历史">
                        <Button
                            type="text"
                            icon={<ReloadOutlined spin={loadingHistory} />}
                            disabled={!sessionId || sending}
                            onClick={() => {
                                if (!sessionId) {
                                    return;
                                }
                                setLoadingHistory(true);
                                fetchAnythingLLMHistory(sessionId)
                                    .then(setMessages)
                                    .catch(() => setError('历史消息加载失败'))
                                    .finally(() => setLoadingHistory(false));
                            }}
                        />
                    </Tooltip>
                    <Tooltip title="重置会话">
                        <Button
                            type="text"
                            danger
                            icon={<DeleteOutlined />}
                            disabled={!sessionId || sending}
                            onClick={handleReset}
                        />
                    </Tooltip>
                </div>
            </div>

            {error && (
                <Alert
                    type="error"
                    message={error}
                    showIcon
                    closable
                    onClose={() => setError('')}
                    style={{ margin: '0 16px 12px' }}
                />
            )}

            <div ref={scrollRef} className="wiki-chat-panel__history">
                {loadingHistory ? (
                    <div className="wiki-chat-panel__center">
                        <Spin />
                    </div>
                ) : messages.length === 0 ? (
                    <div className="wiki-chat-panel__empty">
                        <p>{config.greeting}</p>
                        <div className="wiki-chat-panel__suggestions">
                            {config.defaultMessages.map((message) => (
                                <button
                                    key={message}
                                    type="button"
                                    onClick={() => handleSubmit(undefined, message)}
                                    disabled={sending}
                                >
                                    {message}
                                </button>
                            ))}
                        </div>
                    </div>
                ) : (
                    messages.map((message) => (
                        <ChatMessageBubble key={message.id} message={message} />
                    ))
                )}
            </div>

            <form className="wiki-chat-panel__composer" onSubmit={handleSubmit}>
                <TextArea
                    value={inputValue}
                    disabled={sending}
                    placeholder={config.placeholder}
                    autoSize={{ minRows: 2, maxRows: 5 }}
                    onChange={(event) => setInputValue(event.target.value)}
                    onPressEnter={(event) => {
                        if (!event.shiftKey) {
                            event.preventDefault();
                            handleSubmit();
                        }
                    }}
                />
                <Button
                    type="primary"
                    htmlType="submit"
                    icon={<SendOutlined />}
                    loading={sending}
                    disabled={!inputValue.trim()}
                >
                    发送
                </Button>
            </form>
        </aside>
    );
}

function ChatMessageBubble({ message }: { message: AnythingLLMChatMessage }) {
    const isUser = message.role === 'user';
    const parsedContent = parseThinkContent(message.content);
    const recommendationContent = isUser
        ? { answer: parsedContent.answer, recommendations: [] }
        : parseLearningRecommendations(parsedContent.answer);
    const visibleContent = recommendationContent.answer || (message.pending ? '思考中...' : '');

    return (
        <div className={`wiki-chat-message ${isUser ? 'wiki-chat-message--user' : 'wiki-chat-message--assistant'}`}>
            <div className="wiki-chat-message__bubble">
                {message.error ? (
                    <Alert
                        type="error"
                        message={message.errorMsg || '消息回复失败'}
                        showIcon
                    />
                ) : (
                    <>
                        {!isUser && parsedContent.thoughts.length > 0 && (
                            <details className="wiki-chat-think">
                                <summary>思考过程</summary>
                                <div className="wiki-chat-think__content">
                                    {parsedContent.thoughts.map((thought, index) => (
                                        <ReactMarkdown key={`${thought}-${index}`}>
                                            {thought}
                                        </ReactMarkdown>
                                    ))}
                                </div>
                            </details>
                        )}
                        <ReactMarkdown>
                            {visibleContent}
                        </ReactMarkdown>
                        {!isUser && recommendationContent.recommendations.length > 0 && (
                            <LearningRecommendationCards items={recommendationContent.recommendations} />
                        )}
                    </>
                )}
            </div>
        </div>
    );
}

function LearningRecommendationCards({ items }: { items: LearningRecommendation[] }) {
    return (
        <section className="wiki-learning-recommendations" aria-label="学习推荐">
            <div className="wiki-learning-recommendations__heading">
                <BulbOutlined />
                <span>学习推荐</span>
            </div>
            <div className="wiki-learning-recommendations__list">
                {items.map((item, index) => (
                    <article
                        className="wiki-learning-card"
                        key={`${item.title}-${index}`}
                    >
                        <div className="wiki-learning-card__header">
                            <h3>{item.title}</h3>
                            {item.level && (
                                <span className="wiki-learning-card__level">
                                    {item.level}
                                </span>
                            )}
                        </div>
                        <p>{item.reason}</p>
                        {item.keywords.length > 0 && (
                            <div className="wiki-learning-card__keywords">
                                {item.keywords.map((keyword) => (
                                    <span key={keyword}>{keyword}</span>
                                ))}
                            </div>
                        )}
                    </article>
                ))}
            </div>
        </section>
    );
}

function parseThinkContent(content: string) {
    const thoughts: string[] = [];
    let answer = content;

    // 说明：先提取完整的 <think>...</think> 块，避免思考内容直接混入最终回答。
    answer = answer.replace(/<think>([\s\S]*?)<\/think>/g, (_, thought: string) => {
        const normalizedThought = thought.trim();
        if (normalizedThought) {
            thoughts.push(normalizedThought);
        }

        return '';
    });

    const openThinkIndex = answer.indexOf('<think>');
    if (openThinkIndex >= 0) {
        const beforeThink = answer.slice(0, openThinkIndex);
        const streamingThought = answer.slice(openThinkIndex + '<think>'.length).trim();

        // 说明：流式输出时可能还没有闭合 </think>，这里先把未闭合内容也折叠起来。
        if (streamingThought) {
            thoughts.push(streamingThought.replace(/<\/think>/g, '').trim());
        }

        answer = beforeThink;
    }

    return {
        thoughts,
        answer: answer.replace(/<\/?think>/g, '').trim(),
    };
}

function parseLearningRecommendations(content: string): {
    answer: string;
    recommendations: LearningRecommendation[];
} {
    const startMarker = '<!--LEARNING_RECOMMENDATIONS_START-->';
    const endMarker = '<!--LEARNING_RECOMMENDATIONS_END-->';
    const startIndex = content.indexOf(startMarker);

    if (startIndex >= 0) {
        const endIndex = content.indexOf(endMarker, startIndex + startMarker.length);
        const visibleAnswer = content.slice(0, startIndex).trim();

        if (endIndex < 0) {
            // 说明：流式输出推荐 JSON 时先隐藏半截 JSON，等结束标记到达后再解析展示。
            return {
                answer: visibleAnswer,
                recommendations: [],
            };
        }

        const jsonText = content.slice(startIndex + startMarker.length, endIndex).trim();
        const tail = content.slice(endIndex + endMarker.length).trim();

        return {
            answer: [visibleAnswer, tail].filter(Boolean).join('\n\n'),
            recommendations: normalizeLearningRecommendations(jsonText),
        };
    }

    const fallback = extractFallbackRecommendationJson(content);
    if (!fallback) {
        return {
            answer: content,
            recommendations: [],
        };
    }

    return {
        answer: content.replace(fallback.raw, '').trim(),
        recommendations: normalizeLearningRecommendations(fallback.jsonText),
    };
}

function extractFallbackRecommendationJson(content: string) {
    const fencedMatch = content.match(/```(?:json)?\s*({[\s\S]*?"learningRecommendations"[\s\S]*?})\s*```/);
    if (fencedMatch?.[0] && fencedMatch[1]) {
        return {
            raw: fencedMatch[0],
            jsonText: fencedMatch[1],
        };
    }

    const objectMatch = content.match(/({[\s\S]*"learningRecommendations"[\s\S]*})\s*$/);
    if (objectMatch?.[0] && objectMatch[1]) {
        return {
            raw: objectMatch[0],
            jsonText: objectMatch[1],
        };
    }

    return null;
}

function normalizeLearningRecommendations(jsonText: string): LearningRecommendation[] {
    try {
        const parsed = JSON.parse(jsonText) as unknown;
        if (!isRecord(parsed) || !Array.isArray(parsed.learningRecommendations)) {
            return [];
        }

        const recommendations = parsed.learningRecommendations
            .map((item): LearningRecommendation | null => {
                if (!isRecord(item)) {
                    return null;
                }

                const title = readString(item.title);
                const reason = readString(item.reason);

                if (!title || !reason) {
                    return null;
                }

                return {
                    title,
                    reason,
                    level: readString(item.level),
                    keywords: readStringArray(item.keywords).slice(0, 4),
                };
            })
            // 说明：过滤掉结构不完整的推荐项，并把数组类型收窄为可渲染的推荐数据。
            .filter((item): item is LearningRecommendation => item !== null);

        return recommendations.slice(0, 3);
    } catch {
        // 说明：模型偶尔会输出不完整 JSON，解析失败时只隐藏推荐区，不影响主回答。
        return [];
    }
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readString(value: unknown) {
    return typeof value === 'string' ? value.trim() : '';
}

function readStringArray(value: unknown) {
    if (!Array.isArray(value)) {
        return [];
    }

    return value
        .map(readString)
        .filter(Boolean);
}

function createLocalId() {
    if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
        return crypto.randomUUID();
    }

    // 说明：在非 HTTPS 的非安全上下文中，crypto.randomUUID 可能不可用。
    // 这里使用标准的 UUID v4 算法以保证生成合法的 UUID。
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        const v = c === 'x' ? r : (r & 0x3) | 0x8;
        return v.toString(16);
    });
}
