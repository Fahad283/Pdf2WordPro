import type { Metadata } from 'next';
import { ToolGrid } from '@/components/tool-grid';
import { TOOLS } from '@/lib/tools';

export const metadata: Metadata = { title: 'PDF Tools', description: 'Convert, merge, split, compress, OCR, and protect PDFs with a full set of document tools.', alternates: { canonical: '/tools' } };

export default function Page() {
  return <section className="section-block shell gap-bottom"><div className="page-heading text-left"><h1>PDF tools</h1><p>Choose a tool to convert, organize, or protect your files.</p></div><ToolGrid tools={TOOLS} /></section>;
}
