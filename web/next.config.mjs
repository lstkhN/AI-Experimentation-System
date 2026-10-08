/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  // Playwright and local development use loopback as a separate origin.
  allowedDevOrigins: ['127.0.0.1', 'localhost'],
  turbopack: { root: process.cwd() },
};

export default nextConfig;
