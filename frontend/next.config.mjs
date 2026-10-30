/** @type {import('next').NextConfig} */
const API = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  outputFileTracingRoot: import.meta.dirname,
  // Emit a self-contained server bundle that can run with `node server.js`
  // without a full node_modules tree. Both local dev and start use the API
  // rewrite below to reach the loopback backend.
  output: "standalone",
  async rewrites() {
    // Proxy API calls to the FastAPI backend so the browser sees a same-origin
    // path (/api/*) and streaming responses aren't buffered by a dev proxy.
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default nextConfig;
