import type { Metadata } from "next";
import AntdRegistry from "@/components/AntdRegistry";
import "./globals.css";
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
            </body>
        </html>
    );
}
