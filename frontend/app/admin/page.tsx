import type { Metadata } from 'next';
import { AdminPanel } from '@/components/admin-panel';

export const metadata: Metadata = { title: 'Administrator dashboard', robots: { index: false, follow: false } };

export default function Page() {
  return <section className="section-block shell admin-page"><div className="page-heading text-left"><h1>Administrator dashboard</h1><p>Monitor processing and manage platform settings.</p></div><AdminPanel /></section>;
}
