import Link from 'next/link';
import type { Tool } from '@/lib/tools';

export function ToolGrid({ tools }: { tools: readonly Tool[] }) {
  return <div className="tool-grid">
    {tools.map(({ id, title, description, icon: Icon, color }) => <Link className="tool-card" key={id} href={`/${id}`}>
      <span className={`tool-icon tone-${color}`}><Icon size={23} strokeWidth={1.9} aria-hidden="true" /></span>
      <span className="tool-info"><strong>{title}</strong><span>{description}</span></span>
    </Link>)}
  </div>;
}
