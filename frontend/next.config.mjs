/** @type {import('next').NextConfig} */
const API = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  outputFileTracingRoot: import.meta.dirname,
  // Emit a self-contained server bundle so the production Docker image can run
  // `node server.js` without a full node_modules tree. In production, Caddy —
  // not Next.js — proxies /api/* to the backend, so the rewrite below is a
  // dev-only convenience.
  output: "standalone",
  async rewrites() {
    // Proxy API calls to the FastAPI backend so the browser sees a same-origin
    // path (/api/*) and streaming responses aren't buffered by a dev proxy.
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default nextConfig;
