import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

// GitHub Pages project site: BASE_PATH='/<repo>' in CI, '' locally (plan §10.6, zero-spend: github.io URL only).
const base = process.env.BASE_PATH ?? '';

/** @type {import('@sveltejs/kit').Config} */
export default {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({ pages: 'build', assets: 'build', fallback: undefined, strict: true }),
    paths: { base, relative: false },
    prerender: { handleHttpError: 'fail', handleMissingId: 'fail', entries: ['*'] }
  }
};
