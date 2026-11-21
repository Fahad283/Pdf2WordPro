import type { Metadata } from 'next';
import Link from 'next/link';
import { ChevronDown, CircleCheck, Download, FileCog, LockKeyhole, ScanText, ShieldCheck, TimerReset, Upload } from 'lucide-react';
import { ConversionGraphic } from '@/components/conversion-graphic';
import { ToolGrid } from '@/components/tool-grid';
import { Workbench } from '@/components/workbench';
import { buttonClass } from '@/components/ui/button';
import { TOOLS } from '@/lib/tools';
import { siteName, siteUrl } from '@/lib/seo';

export const metadata: Metadata = {
  alternates: { canonical: '/' },
  openGraph: { title: 'Convert PDF to Word in Seconds', description: 'Make editable Word documents from PDFs with three conversion modes and multilingual OCR.', url: '/' },
};

const how = [
  { icon: Upload, title: 'Upload your PDFs', detail: 'Choose files from your device or drop them into the converter.' },
  { icon: FileCog, title: 'Choose a conversion mode', detail: 'Rebuild the layout, prioritize reading order, or preserve each page as an image.' },
  { icon: Download, title: 'Download your Word files', detail: 'Save each DOCX as it finishes or download a batch as a ZIP archive.' },
];

const faq = [
  ['Can I edit the converted Word document?', 'Editable layout and Flowing text create native Word paragraphs. When the converter recognizes tables, it can rebuild them as Word tables. Visual layout preserves the page as an image.'],
  ['Does it work with scanned PDFs?', 'Yes. Automatic OCR detects scanned pages and tries to recognize their text. Choose the language used in your document, such as English, Urdu, or Arabic.'],
  ['Will the Word document look exactly like my PDF?', 'The converter uses the PDF’s text positions, fonts, images, and tables to reconstruct its layout. Complex pages may need manual cleanup in Word. Visual layout keeps the page appearance as an image.'],
  ['Can I convert several PDFs at once?', 'Yes. Each file is processed independently. Download finished files one at a time or download the completed batch as a ZIP archive.'],
  ['How long are my files kept?', 'Uploads and outputs expire after 60 minutes by default. The upload area shows the current retention period. You can also delete files and results from your session.'],
];

export default function Home() {
  const data = { '@context': 'https://schema.org', '@type': 'WebApplication', name: siteName, url: siteUrl.href, applicationCategory: 'UtilitiesApplication', operatingSystem: 'Any', offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' } };
  return <>
    <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data).replace(/</g, '\\u003c') }} />
    <section className="hero">
      <div className="shell hero-grid">
        <div className="hero-content">
          <h1>Convert PDF to <br className="desktop-break" />Word in <em>Seconds</em></h1>
          <p className="hero-summary">Rebuild text, tables, and images in Word, with OCR for scanned pages.</p>
          <Workbench toolId="pdf-to-word" compact />
        </div>
        <ConversionGraphic />
      </div>
    </section>
    <section className="trust-strip" aria-label="Conversion features"><div className="shell trust-inner">
      <span><LockKeyhole size={18} aria-hidden="true" /> Private processing</span>
      <span><ScanText size={18} aria-hidden="true" /> Multilingual OCR</span>
      <span><CircleCheck size={18} aria-hidden="true" /> Editable DOCX output</span>
    </div></section>
    <section className="shell section-block" aria-labelledby="popular-tools">
      <div className="section-heading section-heading-row"><div><h2 id="popular-tools">Popular PDF tools</h2><p>Convert, organize, and protect your documents in one place.</p></div><Link className={buttonClass('outline')} href="/tools">View all tools</Link></div>
      <ToolGrid tools={TOOLS.slice(0, 6)} />
    </section>
    <section className="section-block tinted-section" aria-labelledby="how-heading"><div className="shell">
      <div className="section-heading"><h2 id="how-heading">How to convert PDF to Word</h2></div>
      <div className="process-grid">{how.map(({ icon: Icon, title, detail }) => <article key={title}><span className="tool-icon tone-blue"><Icon size={22} aria-hidden="true" /></span><h3>{title}</h3><p>{detail}</p></article>)}</div>
    </div></section>
    <section className="shell section-block privacy-block" aria-labelledby="privacy-heading">
      <div><span className="privacy-shield"><ShieldCheck size={27} aria-hidden="true" /></span><h2 id="privacy-heading">Your documents stay private</h2><p>Files are processed in isolated jobs. Download links are restricted to your session or account.</p><Link className={buttonClass('outline')} href="/privacy">Privacy and retention</Link></div>
      <div className="privacy-facts"><article><TimerReset size={22} aria-hidden="true" /><div><h3>Automatic expiry</h3><p>Uploads and converted files expire after 60 minutes by default.</p></div></article><article><LockKeyhole size={22} aria-hidden="true" /><div><h3>Delete at any time</h3><p>Remove uploads and conversion results when you are finished.</p></div></article></div>
    </section>
    <section className="tinted-section section-block" aria-labelledby="faq-heading"><div className="shell faq-grid">
      <div className="section-heading"><h2 id="faq-heading">Frequently asked questions</h2></div>
      <div className="faq-items">{faq.map(([question, answer]) => <details key={question}><summary>{question}<ChevronDown size={18} aria-hidden="true" /></summary><p>{answer}</p></details>)}</div>
    </div></section>
  </>;
}
