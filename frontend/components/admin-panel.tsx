'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ChartNoAxesColumn, LoaderCircle } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { api, ApiError, errorText, json, type Config, type Metrics, type User } from '@/lib/api';
import { fileSize } from '@/lib/utils';
import { Button, buttonClass } from './ui/button';

const adminSchema = z.object({
  max_upload_mb: z.number().int().min(1).max(256), max_pages: z.number().int().min(1).max(2000), max_batch_files: z.number().int().min(1).max(30),
  retention_minutes: z.number().int().min(1).max(1440), daily_conversion_limit: z.number().int().min(1).max(100000),
  ocr_languages: z.string().regex(/^\s*[a-z]{3}(?:_[a-z]{3,8})?\s*(?:,\s*[a-z]{3}(?:_[a-z]{3,8})?\s*){0,29}$/, 'Enter comma-separated Tesseract language codes.'),
});
type AdminFields = z.infer<typeof adminSchema>;

const numberFields = [
  ['max_upload_mb', 'Maximum upload size in MB', 256], ['max_pages', 'Maximum pages per file', 2000], ['max_batch_files', 'Maximum files per batch', 30],
  ['retention_minutes', 'Retention in minutes', 1440], ['daily_conversion_limit', 'Daily conversion limit', 100000],
] as const;

function SettingsForm({ config }: { config: Config }) {
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const { register, handleSubmit, reset, formState: { errors, isSubmitting } } = useForm<AdminFields>({
    resolver: zodResolver(adminSchema), defaultValues: { ...config, ocr_languages: config.ocr_languages.join(', ') },
  });
  const submit = handleSubmit(async (data) => {
    setMessage(''); setError('');
    try {
      const next = await api<Config>('/admin/settings', json('PATCH', { ...data, ocr_languages: data.ocr_languages.split(',').map((item) => item.trim()) }));
      reset({ ...next, ocr_languages: next.ocr_languages.join(', ') });
      setMessage('Settings saved.');
    } catch (caught) { setError(errorText(caught)); }
  });
  return <section className="account-card"><h2>Processing settings</h2><form className="admin-form" noValidate onSubmit={(event) => void submit(event)}>
    {numberFields.map(([field, label, max]) => <label className="field-stack" key={field}>{label}<input className="field-input" type="number" min={1} max={max} {...register(field, { valueAsNumber: true })} />{errors[field] && <small className="text-error">Enter a whole number from 1 to {max.toLocaleString()}.</small>}</label>)}
    <label className="field-stack">OCR language codes<input className="field-input" {...register('ocr_languages')} />{errors.ocr_languages && <small className="text-error">{errors.ocr_languages.message}</small>}</label>
    {(message || error) && <p className={error ? 'inline-error' : 'success-text'} role={error ? 'alert' : 'status'}>{error || message}</p>}
    <div className="work-actions"><Button type="submit" disabled={isSubmitting}>Save settings</Button></div>
  </form></section>;
}

export function AdminPanel() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [denied, setDenied] = useState(false);
  const [updatingUser, setUpdatingUser] = useState<string | null>(null);

  async function load() {
    setError('');
    try {
      const [nextMetrics, nextConfig, nextUsers] = await Promise.all([api<Metrics>('/admin/metrics'), api<Config>('/admin/settings'), api<{ users: User[] }>('/admin/users')]);
      setMetrics(nextMetrics); setConfig(nextConfig); setUsers(nextUsers.users);
    } catch (caught) {
      if (caught instanceof ApiError && (caught.status === 401 || caught.status === 403)) setDenied(true);
      else setError(errorText(caught));
    } finally { setLoading(false); }
  }

  useEffect(() => { void load(); }, []);

  async function updateUser(id: string, changes: Partial<Pick<User, 'status' | 'plan'>>) {
    setUpdatingUser(id); setError('');
    try {
      const updated = await api<User>(`/admin/users/${id}`, json('PATCH', changes));
      setUsers((current) => current.map((candidate) => candidate.id === updated.id ? updated : candidate));
    } catch (caught) { setError(errorText(caught)); }
    finally { setUpdatingUser(null); }
  }

  if (loading) return <p className="loading-state" role="status"><LoaderCircle size={19} className="spinner" aria-hidden="true" /> Loading system metrics</p>;
  if (denied) return <div className="account-card"><p>Sign in with an administrator account to open this dashboard.</p><Link href="/account" className={buttonClass('outline')}>Account</Link></div>;
  const cards: [string, string | number][] = metrics ? [
    ['Users', metrics.total_users], ['Uploads', metrics.total_uploads], ['Conversions', metrics.total_conversions],
    ['Successful', metrics.successful_conversions], ['Failed', metrics.failed_conversions], ['Active jobs', metrics.active_jobs],
    ['Queue status', metrics.queue_status], ['Average processing time', metrics.average_conversion_seconds === null ? '—' : `${metrics.average_conversion_seconds.toFixed(1)} s`],
    ['Storage used', fileSize(metrics.storage_bytes)], ['OCR jobs', metrics.ocr_jobs], ['System health', metrics.system_health],
  ] : [];
  return <div className="admin-area">
    {error && <p className="inline-error" role="alert">{error}</p>}
    <div className="work-actions admin-refresh"><Link href="/benchmark" className={buttonClass('outline')}><ChartNoAxesColumn size={17} aria-hidden="true" /> Benchmark dashboard</Link><Button variant="outline" onClick={() => void load()}>Refresh dashboard</Button></div>
    <div className="metrics-grid">{cards.map(([label, value]) => <article className="metric-card" key={label}><h2>{label}</h2><p>{value}</p></article>)}</div>
    {config && <SettingsForm key={JSON.stringify(config)} config={config} />}
    <section className="account-card"><h2>User accounts</h2>{users.length ? <div className="table-scroll"><table className="admin-table"><thead><tr><th scope="col">Email</th><th scope="col">Role</th><th scope="col">Status</th><th scope="col">Plan</th></tr></thead><tbody>
      {users.map((user) => <tr key={user.id}><th scope="row">{user.email}</th><td>{user.role}</td><td><select className="field-input" aria-label={`Status for ${user.email}`} value={user.status} disabled={updatingUser !== null || user.role === 'admin'} onChange={(event) => void updateUser(user.id, { status: event.target.value as User['status'] })}><option value="active">Active</option><option value="suspended">Suspended</option></select></td><td><select className="field-input" aria-label={`Plan for ${user.email}`} value={user.plan} disabled={updatingUser !== null} onChange={(event) => void updateUser(user.id, { plan: event.target.value as User['plan'] })}><option value="free">Free</option><option value="premium">Premium</option></select></td></tr>)}
    </tbody></table></div> : <p>No user accounts found.</p>}</section>
    <section className="account-card"><h2>Recent errors</h2>{metrics?.recent_errors.length ? <ul className="admin-errors">{metrics.recent_errors.map((entry) => <li key={entry.id}><strong>{entry.tool}</strong><span>{entry.error}</span><time dateTime={entry.created_at}>{new Date(entry.created_at).toLocaleString()}</time></li>)}</ul> : <p>No recent errors.</p>}</section>
  </div>;
}
