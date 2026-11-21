import Link from 'next/link';
import { Brand } from './brand';
import { TOOLS } from '@/lib/tools';

export function Footer() {
  return <footer className="site-footer">
    <div className="shell footer-main">
      <div><Brand /><p>Convert, organize, and protect your documents.</p></div>
      <nav aria-label="Footer PDF tools"><h2>Popular tools</h2>{TOOLS.slice(0, 6).map(({ id, title }) => <Link key={id} href={`/${id}`}>{title}</Link>)}</nav>
      <nav aria-label="Footer platform"><h2>Platform</h2><Link href="/tools">All PDF tools</Link><Link href="/pricing">Pricing</Link><Link href="/account">Account and history</Link><Link href="/privacy">Privacy and file retention</Link></nav>
    </div>
    <div className="shell footer-end">PDF to Word Pro</div>
  </footer>;
}
