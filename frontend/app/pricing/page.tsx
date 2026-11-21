import type { Metadata } from 'next';
import Link from 'next/link';
import { CircleCheck, Layers3, UsersRound } from 'lucide-react';
import { buttonClass } from '@/components/ui/button';

export const metadata: Metadata = { title: 'Pricing', description: 'Use PDF tools for free and see what a future premium plan is intended to include.', alternates: { canonical: '/pricing' } };

export default function Page() {
  return <section className="section-block shell pricing-page">
    <div className="page-heading"><h1>Plans and pricing</h1><p>Start converting PDFs for free.</p></div>
    <div className="pricing-grid">
      <article className="pricing-card"><Layers3 size={26} aria-hidden="true" /><h2>Free</h2><p className="plan-price">$0</p><p>For everyday document work.</p>
        <ul>{['PDF to Word conversion', 'Multilingual OCR', 'PDF editing tools', 'Optional account and job history'].map((feature) => <li key={feature}><CircleCheck size={17} aria-hidden="true" />{feature}</li>)}</ul>
        <Link className={buttonClass()} href="/pdf-to-word">Start converting</Link>
      </article>
      <article className="pricing-card"><UsersRound size={26} aria-hidden="true" /><h2>Premium</h2><p className="plan-price plan-future">Planned</p><p>For frequent or larger conversions.</p>
        <ul>{['Higher conversion and upload limits', 'Priority processing', 'Expanded history options', 'API access'].map((feature) => <li key={feature}><CircleCheck size={17} aria-hidden="true" />{feature}</li>)}</ul>
      </article>
    </div>
  </section>;
}
