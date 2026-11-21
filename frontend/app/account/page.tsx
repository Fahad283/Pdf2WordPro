import type { Metadata } from 'next';
import { AccountPanel } from '@/components/account-panel';

export const metadata: Metadata = { title: 'Account and conversion history', robots: { index: false, follow: false } };

export default function Page() {
  return <section className="section-block shell account-page"><div className="page-heading"><h1>Account and history</h1><p>Sign in to manage your account and find recent conversions.</p></div><AccountPanel /></section>;
}
