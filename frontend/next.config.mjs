/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // `output: 'standalone'` is intentionally NOT set. Vercel builds Next.js
  // natively and does not use it, and enabling it makes `next start`
  // unsupported, which breaks `npm run start` for local production runs and
  // for any self-hosted deployment that follows the README.
  eslint: {
    // Linting must never block a production build.
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
