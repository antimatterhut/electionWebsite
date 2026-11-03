import { base } from '$app/paths';
import { RACE_STATES } from '$lib/states';
import { siteUrl } from '$lib/seo';

export const prerender = true;

export function GET() {
  const paths = ['/', '/methodology', '/about', ...RACE_STATES.map((s) => `/state/${s}`)];
  const body = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${paths
    .map((p) => `  <url><loc>${siteUrl}${base}${p === '/' ? '/' : p}</loc></url>`)
    .join('\n')}\n</urlset>\n`;
  return new Response(body, { headers: { 'Content-Type': 'application/xml' } });
}
