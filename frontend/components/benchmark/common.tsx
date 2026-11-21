import type { ReactNode } from 'react';
import { Database, LoaderCircle } from 'lucide-react';
import { active, label, metric } from '@/lib/benchmarks';

export function Panel({ title, description, action, children, className = '' }: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return <section className={`bench-panel ${className}`}>
    <div className="bench-panel-head">
      <div><h2>{title}</h2>{description && <p>{description}</p>}</div>
      {action && <div className="bench-actions">{action}</div>}
    </div>
    {children}
  </section>;
}

export function Loading({ label: text = 'Loading benchmark data' }: { label?: string }) {
  return <p className="bench-loading" role="status">
    <LoaderCircle size={19} className="spinner" aria-hidden="true" />{text}
  </p>;
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return <div className="bench-empty">
    <span aria-hidden="true" className="bench-empty-icon"><Database size={23} strokeWidth={1.8} /></span>
    <strong>{title}</strong>{children && <div>{children}</div>}{action}
  </div>;
}

export function ErrorNotice({ children }: { children: ReactNode }) {
  return children ? <p className="inline-error bench-error" role="alert">{children}</p> : null;
}

export function Status({ value, passed }: { value: string; passed?: boolean | null }) {
  const negative = passed === false || ['failed', 'error', 'cancelled', 'rejected'].includes(value);
  const positive = passed === true || ['completed', 'ready', 'passed', 'frozen'].includes(value);
  return <span className={`bench-status ${negative ? 'is-negative' : positive ? 'is-positive' : active(value) ? 'is-active' : ''}`}>
    {active(value) && <span aria-hidden="true" className="bench-status-dot" />}
    {passed === true ? 'Passed' : passed === false ? 'Failed' : label(value)}
  </span>;
}

export function Bar({ value, max = 1, className = '' }: { value: number; max?: number; className?: string }) {
  const width = Math.max(0, Math.min(100, 100 * value / Math.max(max, Number.EPSILON)));
  return <div aria-hidden="true" className={`bench-track ${className}`}><span style={{ width: `${width}%` }} /></div>;
}

export function scalar(value: unknown) {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  const number = metric(value);
  if (number !== undefined) return Number.isInteger(number) ? number.toLocaleString() : number.toLocaleString(undefined, { maximumFractionDigits: 4 });
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.every((item) => typeof item !== 'object') ? value.join(', ') || '—' : JSON.stringify(value);
  return JSON.stringify(value);
}

export function Facts({ entries }: { entries: [string, ReactNode][] }) {
  if (!entries.length) return null;
  return <dl className="bench-facts">{entries.map(([key, value]) =>
    <div key={key}><dt>{key}</dt><dd>{value}</dd></div>,
  )}</dl>;
}

export function NoticeList({ title, items, critical = false }: { title: string; items?: string[]; critical?: boolean }) {
  if (!items?.length) return null;
  return <div className={`bench-notices ${critical ? 'is-critical' : ''}`}><h3>{title}</h3><ul>{items.map((value, index) => <li key={index}>{value}</li>)}</ul></div>;
}
