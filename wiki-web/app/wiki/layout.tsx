'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button, ConfigProvider, Layout, Tooltip, theme } from 'antd';
import { MoonOutlined, SunOutlined } from '@ant-design/icons';
import WikiSidebar from '@/components/WikiSidebar';
import WikiSearchBar from '@/components/WikiSearchBar';
import WikiChatPanel from '@/components/WikiChatPanel';
import { TreeNode } from '@/types';
import { getTree } from '@/lib/api';
import { getAuthToken, installAuthExpirationHandler } from '@/lib/auth-token';

const { Content } = Layout;

export default function WikiLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    const router = useRouter();
    const [tree, setTree] = useState<TreeNode[]>([]);
    const [loading, setLoading] = useState(true);
    const [isDark, setIsDark] = useState(false);
    const [themeReady, setThemeReady] = useState(false);

    useEffect(() => {
        installAuthExpirationHandler();
    }, []);

    // Auth gate for Wiki content
    useEffect(() => {
        const token = getAuthToken();
        if (!token) {
            router.replace('/login');
        }
    }, [router]);

    useEffect(() => {
        getTree()
            .then(setTree)
            .catch(console.error)
            .finally(() => setLoading(false));
    }, []);

    useEffect(() => {
        // 说明：
        // 首次挂载后再从本地存储和 html class 同步主题，
        // 保证服务端和客户端首帧一致，避免 hydration 报错。
        const syncThemeFromStorage = () => {
            const storedTheme = window.localStorage.getItem('wiki-theme');
            const nextDark = storedTheme
                ? storedTheme === 'dark'
                : document.documentElement.classList.contains('dark');

            setIsDark((prev) => (prev === nextDark ? prev : nextDark));
            setThemeReady(true);
        };

        const handleStorage = (event: StorageEvent) => {
            if (event.key && event.key !== 'wiki-theme') {
                return;
            }

            syncThemeFromStorage();
        };

        const handleThemeEvent = () => {
            syncThemeFromStorage();
        };

        syncThemeFromStorage();

        window.addEventListener('storage', handleStorage);
        window.addEventListener('wiki-theme-change', handleThemeEvent);

        return () => {
            window.removeEventListener('storage', handleStorage);
            window.removeEventListener('wiki-theme-change', handleThemeEvent);
        };
    }, []);

    useEffect(() => {
        // 说明：
        // 统一在状态变化时同步 html 根节点 class，确保全局 CSS 变量、
        // 第三方组件样式和页面内联样式都跟当前主题保持一致。
        if (!themeReady) {
            return;
        }

        document.documentElement.classList.toggle('dark', isDark);
    }, [isDark, themeReady]);

    const handleThemeToggle = () => {
        const nextDark = !isDark;
        setIsDark(nextDark);
        window.localStorage.setItem('wiki-theme', nextDark ? 'dark' : 'light');
        window.dispatchEvent(new Event('wiki-theme-change'));
    };

    return (
        <ConfigProvider
            theme={{
                algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
                token: {
                    colorPrimary: '#cc785c',
                    fontFamily: 'Inter, -apple-system, sans-serif',
                    borderRadius: 8,
                    colorBgContainer: isDark ? '#252320' : '#faf9f5',
                    colorBgLayout: isDark ? '#181715' : '#faf9f5',
                },
            }}
        >
            <Layout
                style={{
                    height: '100vh',
                    minWidth: 1180,
                    overflow: 'hidden',
                    background: 'var(--color-background)',
                }}
            >
                <div className="wiki-three-column-shell">
                    <aside className="wiki-left-panel">
                        <div className="wiki-left-panel__brand">
                            智能学习助手
                        </div>
                        <div className="wiki-left-panel__nav">
                            <WikiSidebar tree={tree} loading={loading} />
                        </div>
                        <div className="wiki-left-panel__footer">
                            <Tooltip title={isDark ? '切换到亮色模式' : '切换到深色模式'} placement="right">
                                <Button
                                    type="text"
                                    icon={isDark ? <SunOutlined /> : <MoonOutlined />}
                                    onClick={handleThemeToggle}
                                    className="wiki-theme-toggle"
                                >
                                    {isDark ? '亮色模式' : '深色模式'}
                                </Button>
                            </Tooltip>
                        </div>
                    </aside>

                    <section className="wiki-center-panel">
                        <div className="wiki-center-panel__search">
                            <WikiSearchBar tree={tree} />
                        </div>
                        <Content className="wiki-center-panel__content">
                            {children}
                        </Content>
                    </section>

                    <WikiChatPanel />
                </div>
            </Layout>
        </ConfigProvider>
    );
}
