import path from "node:path";
import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// 说明：
// 前端目录不再保留独立 .env。直接运行 `npm run dev/build` 时，
// 这里从仓库根目录加载统一 .env，保持本地开发和 compose 启动的配置来源一致。
loadEnvConfig(path.resolve(process.cwd(), '..'));

const nextConfig: NextConfig = {
    // 说明：standalone 产物用于 Docker 运行阶段，只复制必要的 Next.js 服务端文件和依赖。
    output: 'standalone',
    experimental: {
        optimizePackageImports: ['antd', '@ant-design/icons'],
    },
    transpilePackages: ['antd'],
    async rewrites() {
        return [
            {
                // 说明：浏览器只访问 wiki-web 端口，再由 Next.js 在 Docker 内部转发到后端。
                source: '/wiki-api/:path*',
                destination: 'http://wiki-backend:8000/:path*',
            },
        ];
    },
};

export default nextConfig;
