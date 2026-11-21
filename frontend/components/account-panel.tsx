'use client';

import Link from 'next/link';
import { Download, FileText, LoaderCircle, LogOut, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { api, ApiError, errorText, isActive, jobUrl, json, type Job, type User } from '@/lib/api';
import { getTool } from '@/lib/tools';
import { Button, buttonClass } from './ui/button';

const credentials = z.object({ email: z.email('Enter a valid email address.').max(254, 'Use at most 254 characters.'), password: z.string().min(1, 'Enter your password.').max(128, 'Use at most 128 characters.') });

type Credentials = z.infer<typeof credentials>;

function AuthForm({ onSignedIn }: { onSignedIn: () => Promise<void> }) {
  const [register, setRegister] = useState(false);
  const [error, setError] = useState('');
  const { register: field, handleSubmit, resetField, formState: { errors, isSubmitting } } = useForm<Credentials>({ resolver: zodResolver(credentials) });

  const submit = handleSubmit(async (data) => {
    setError('');
    if (register && data.password.length < 12) { setError('Use at least 12 characters for your password.'); return; }
    try {
      await api<User>(register ? '/auth/register' : '/auth/login', json('POST', data));
      resetField('password');
      await onSignedIn();
    } catch (caught) { setError(errorText(caught)); }
  });

  return <div className="account-card">
    <div className="account-tabs" aria-label="Account action">
      <button type="button" aria-pressed={!register} onClick={() => { setRegister(false); setError(''); resetField('password'); }}>Sign in</button>
      <button type="button" aria-pressed={register} onClick={() => { setRegister(true); setError(''); resetField('password'); }}>Create account</button>
    </div>
    <form className="auth-form" onSubmit={(event) => void submit(event)} noValidate>
      <label className="field-stack">Email address<input className="field-input" type="email" autoComplete="email" aria-invalid={Boolean(errors.email)} {...field('email')} />{errors.email && <small className="text-error">{errors.email.message}</small>}</label>
      <label className="field-stack">Password<input className="field-input" type="password" autoComplete={register ? 'new-password' : 'current-password'} aria-invalid={Boolean(errors.password)} {...field('password')} />{errors.password && <small className="text-error">{errors.password.message}</small>}</label>
      {error && <p className="inline-error" role="alert">{error}</p>}
      <Button type="submit" disabled={isSubmitting}>{isSubmitting && <LoaderCircle size={17} className="spinner" aria-hidden="true" />}{register ? 'Create account' : 'Sign in'}</Button>
    </form>
  </div>;
}

export function AccountPanel() {
  const [user, setUser] = useState<User | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  async function refresh() {
    setError('');
    const identity = await api<User>('/auth/me').catch((caught) => {
      if (caught instanceof ApiError && caught.status === 401) return null;
      throw caught;
    });
    setUser(identity);
    const result = await api<{ jobs: Job[] }>('/conversions/history');
    setJobs(result.jobs);
  }

  useEffect(() => {
    refresh().catch((caught) => setError(errorText(caught))).finally(() => setLoading(false));
  }, []);

  async function logout() {
    try { await api('/auth/logout', json('POST')); await refresh(); }
    catch (caught) { setError(errorText(caught)); }
  }

  async function remove(id: string) {
    try { await api(`/conversions/${id}`, { method: 'DELETE' }); setJobs((current) => current.filter((job) => job.id !== id)); }
    catch (caught) { setError(errorText(caught)); }
  }

  if (loading) return <p className="loading-state" role="status"><LoaderCircle className="spinner" size={19} aria-hidden="true" /> Loading your account</p>;
  return <div className="account-area">
    {error && <p className="inline-error" role="alert">{error}</p>}
    {user ? <div className="account-card signed-in"><div><h2>{user.email}</h2><p>{user.plan === 'premium' ? 'Premium plan' : 'Free plan'}</p></div>
      <div className="work-actions">{user.role === 'admin' && <Link className={buttonClass('outline')} href="/admin">Admin dashboard</Link>}
        <Button variant="outline" onClick={() => void logout()}><LogOut size={17} aria-hidden="true" /> Sign out</Button></div>
    </div> : <AuthForm onSignedIn={refresh} />}
    <section className="account-card history-card"><div className="work-head"><h2>Conversion history</h2><Button variant="ghost" className="action-button" onClick={() => void refresh().catch((caught) => setError(errorText(caught)))}>Refresh</Button></div>
      {jobs.length ? <div className="job-list">{jobs.map((job) => {
        const name = job.input_files[0]?.original_filename ?? job.output_filename ?? 'Document';
        return <article className="job-row" key={job.id}><div className="job-heading"><span className="file-icon"><FileText size={20} aria-hidden="true" /></span><div className="file-info"><strong title={name}>{name}</strong><small>{getTool(job.tool)?.title ?? job.tool} · {job.status} · {new Date(job.created_at).toLocaleDateString()}</small></div>
          {job.status === 'completed' && new Date(job.expires_at).getTime() > Date.now() && <a className={buttonClass('outline', 'action-button download-button')} href={jobUrl(job.id, 'download')} download aria-label={`Download ${name}`}><Download size={17} aria-hidden="true" /><span>Download</span></a>}
          {!isActive(job) && <button className="icon-button" onClick={() => void remove(job.id)} aria-label={`Delete ${name}`}><Trash2 size={17} aria-hidden="true" /></button>}</div>
          {job.error && <p className="inline-error">{job.error}</p>}
        </article>;
      })}</div> : <p>No recent conversions in this {user ? 'account' : 'session'}.</p>}
    </section>
  </div>;
}
