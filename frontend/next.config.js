/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // WebSocket connections are opened at runtime, not during build.
  // Keep Next.js from trying to statically generate the lesson room.
  output: "standalone",
};

module.exports = nextConfig;
