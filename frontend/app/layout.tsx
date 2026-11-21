import type { Metadata } from 'next';
import { Header } from '@/components/header';
import { Footer } from '@/components/footer';
import { siteName, siteUrl } from '@/lib/seo';
import './globals.css';

export const metadata: Metadata = {
  metadataBase: siteUrl,
  title: { default: 'PDF to Word Pro | Convert PDF to Editable Word', template: `%s | ${siteName}` },
  description: 'Convert PDFs to editable Word documents, recognize scanned text with OCR, and organize PDF pages in your browser.',
  openGraph: { type: 'website', siteName },
};

const themeScript = `try{const saved=localStorage.getItem('pdf-pro-theme');document.documentElement.dataset.theme=saved==='dark'||saved==='light'?saved:matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}catch{}`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en" suppressHydrationWarning>
    <head><script dangerouslySetInnerHTML={{ __html: themeScript }} /></head>
    <body>
      <a href="#main" className="skip-link">Skip to content</a>
      <Header /><main id="main">{children}</main><Footer />
    </body>
  </html>;
}
