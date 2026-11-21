import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Workbench } from '@/components/workbench';
import { getTool, TOOLS } from '@/lib/tools';

export function generateStaticParams() { return TOOLS.map(({ id }) => ({ tool: id })); }
export const dynamicParams = false;

type ToolPage = { params: Promise<{ tool: string }> };

export async function generateMetadata({ params }: ToolPage): Promise<Metadata> {
  const tool = getTool((await params).tool);
  if (!tool) return {};
  return { title: tool.title, description: tool.detail, alternates: { canonical: `/${tool.id}` }, openGraph: { title: tool.title, description: tool.detail, url: `/${tool.id}` } };
}

export default async function Page({ params }: ToolPage) {
  const tool = getTool((await params).tool);
  if (!tool) notFound();
  const Icon = tool.icon;
  return <section className="tool-page section-block">
    <div className="shell">
      <nav className="breadcrumbs" aria-label="Breadcrumb"><Link href="/">Home</Link><span aria-hidden="true">/</span><Link href="/tools">PDF Tools</Link><span aria-hidden="true">/</span><span aria-current="page">{tool.title}</span></nav>
      <div className="tool-page-content">
        <div className="page-heading"><span className={`tool-icon tone-${tool.color}`}><Icon size={27} aria-hidden="true" /></span><h1>{tool.title}</h1><p>{tool.detail}</p></div>
        <Workbench key={tool.id} toolId={tool.id} />
      </div>
    </div>
  </section>;
}
