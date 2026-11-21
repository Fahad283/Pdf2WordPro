import type { MetadataRoute } from 'next';
import { TOOLS } from '@/lib/tools';
import { siteUrl } from '@/lib/seo';

export default function sitemap(): MetadataRoute.Sitemap {
  return ['/', '/tools', '/pricing', '/privacy', ...TOOLS.map(({ id }) => `/${id}`)].map((path) => ({ url: new URL(path, siteUrl).href }));
}
