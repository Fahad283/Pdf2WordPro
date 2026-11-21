import Link from 'next/link';
import { FileText } from 'lucide-react';

export function Brand() {
  return <Link href="/" className="brand" aria-label="PDF to Word Pro home">
    <span className="brand-mark"><FileText aria-hidden="true" size={21} strokeWidth={2.3} /></span>
    <span>PDF to Word <span className="brand-accent">Pro</span></span>
  </Link>;
}
