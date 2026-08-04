import type { Metadata } from "next";
import AntdRegistry from "@/components/AntdRegistry";
import "./globals.css";
import Script from "next/script";
export const metadata: Metadata = {
    title: "智能学习助手",
    description: "智能学习助手知识库与文档门户",
};

export default function RootLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <html lang="zh-CN" suppressHydrationWarning>
            <head>
                <link
                    href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;700;800&family=Inter:wght@400;500;600&display=swap"
                    rel="stylesheet"
                />
                <script
                    dangerouslySetInnerHTML={{
                        __html: `
                            (() => {
                                try {
                                    const savedTheme = window.localStorage.getItem('wiki-theme');
                                    const isDark = savedTheme === 'dark';
                                    document.documentElement.classList.toggle('dark', isDark);
                                } catch (_) {
                                    document.documentElement.classList.remove('dark');
                                }
                            })();
                        `,
                    }}
                />
            </head>
            <body>
                <AntdRegistry>{children}</AntdRegistry>
<script data-embed-id="593d5b3b-4f7c-4c25-abea-9636a67b40bc" data-base-api-url="http://127.0.0.1:3001/api/embed" src="http://127.0.0.1:3001/embed/anythingllm-chat-widget.min.js"/>     
</body>
        </html>
    );
}
