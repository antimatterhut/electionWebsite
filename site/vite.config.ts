import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [sveltekit()],
  server: { fs: { allow: ['..'] } }, // docs/methodology.md lives outside site/
  test: { include: ['tests/unit/**/*.test.ts'], environment: 'node' }
});
