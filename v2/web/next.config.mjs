const apiProxyTarget =
  process.env.FUNNEL_V2_API_PROXY_TARGET ||
  process.env.FUNNEL_V2_API_BASE_URL ||
  "http://127.0.0.1:8211";

/** @type {import('next').NextConfig} */
const nextConfig = {
  typedRoutes: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiProxyTarget}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
