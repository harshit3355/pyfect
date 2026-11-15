import { createMDX } from 'fumadocs-mdx/next';

const withMDX = createMDX();

/** @type {import('next').NextConfig} */
const config = {
  reactStrictMode: true,
  experimental: {
    // A page that fails or times out fails the build. Next retries it by default, which
    // once hid pages taking over a minute each.
    staticGenerationRetryCount: 0,
  },
  async redirects() {
    return [{ source: '/', destination: '/docs', permanent: false }];
  },
};

export default withMDX(config);
