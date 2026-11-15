import { availableParallelism } from 'node:os';
import { createMDX } from 'fumadocs-mdx/next';

const withMDX = createMDX();

/** @type {import('next').NextConfig} */
const config = {
  reactStrictMode: true,
  experimental: {
    // Prerendering the ~8400 pages is the build's longest step, and the main process waits
    // through it: one worker per CPU, not Next's default of one fewer.
    cpus: availableParallelism(),
  },
  async redirects() {
    return [{ source: '/', destination: '/docs', permanent: false }];
  },
};

export default withMDX(config);
