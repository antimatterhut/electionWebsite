// Absolute site origin for canonical/OG URLs. Set VITE_SITE_URL (e.g. https://<owner>.github.io) in CI; when unset the
// tags fall back to path-only URLs and the sitemap says so (plan §10.6: github.io URL only, no custom domain).
export const siteUrl: string = (import.meta.env?.VITE_SITE_URL as string | undefined)?.replace(/\/$/, '') ?? '';
