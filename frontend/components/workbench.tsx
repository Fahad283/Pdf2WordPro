'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Archive, CircleAlert, CircleCheck, CloudUpload, Download, FileText, LoaderCircle, LockKeyhole, RotateCcw, Trash2, Upload, X } from 'lucide-react';
import { batchUrl, errorText, isActive, jobUrl, type Job } from '@/lib/api';
import { getTool, isCombined, type ToolId } from '@/lib/tools';
import { fileSize } from '@/lib/utils';
import { useWorkbench } from '@/hooks/use-workbench';
import { ConversionSettings, defaults, makeSettings, type Options } from './conversion-settings';
import { Button, buttonClass } from './ui/button';

const jobStatus = { queued: 'Queued', processing: 'Processing', completed: 'Ready to download', failed: 'Failed', cancelled: 'Cancelled' };

function JobRow({ job, change }: { job: Job; change: (id: string, action: 'retry' | 'cancel' | 'delete', password?: string) => Promise<void> }) {
  const [pending, setPending] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [password, setPassword] = useState('');
  const requiresPassword = job.tool === 'protect-pdf' || job.tool === 'unlock-pdf' || job.input_files.some((file) => file.encrypted);
  const name = job.input_files.length > 1 ? `${job.input_files.length} files` : job.input_files[0]?.original_filename ?? 'Document';
  const action = async (kind: 'retry' | 'cancel' | 'delete') => {
    setPending(true);
    await change(job.id, kind, kind === 'retry' ? password : undefined);
    setPending(false);
    setRetrying(false);
    setPassword('');
  };

  return <article className="job-row">
    <div className="job-heading">
      <span className={`file-icon ${job.status === 'completed' ? 'success-icon' : ''}`}>{job.status === 'completed' ? <CircleCheck size={20} aria-hidden="true" /> : <FileText size={20} aria-hidden="true" />}</span>
      <div className="file-info"><strong title={name}>{name}</strong><small>{jobStatus[job.status]}{isActive(job) && ` · ${job.progress}%`}</small></div>
      {job.status === 'completed' && <a className={buttonClass('outline', 'action-button download-button')} href={jobUrl(job.id, 'download')} download aria-label={`Download result for ${name}`}><Download size={16} aria-hidden="true" /><span>Download</span></a>}
      {isActive(job) && <Button className="action-button" variant="outline" onClick={() => void action('cancel')} disabled={pending}>Cancel</Button>}
      {(job.status === 'failed' || job.status === 'cancelled') && <Button className="action-button" variant="outline" onClick={() => { if (requiresPassword) setRetrying(true); else void action('retry'); }} disabled={pending}><RotateCcw size={15} aria-hidden="true" /> Retry</Button>}
      {!isActive(job) && <button className="icon-button file-action" type="button" onClick={() => void action('delete')} disabled={pending} aria-label={`Delete job for ${name}`}><Trash2 size={17} aria-hidden="true" /></button>}
    </div>
    {isActive(job) && <progress className="job-progress" value={job.progress} max={100} aria-label={`Conversion progress for ${name}`}>{job.progress}%</progress>}
    {job.error && <p className="inline-error"><CircleAlert size={17} aria-hidden="true" />{job.error}</p>}
    {!!job.warnings.length && <details className="warnings"><summary>Conversion notes ({job.warnings.length})</summary><ul>{job.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></details>}
    {retrying && <form className="retry-form" onSubmit={(event) => { event.preventDefault(); void action('retry'); }}>
      <label className="field-stack">PDF password<input autoComplete="off" className="field-input" required type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      <Button type="submit" disabled={pending}>Retry</Button><Button variant="ghost" onClick={() => { setRetrying(false); setPassword(''); }}>Close</Button>
    </form>}
  </article>;
}

export function Workbench({ toolId, compact = false }: { toolId: ToolId; compact?: boolean }) {
  const tool = getTool(toolId)!;
  const fileInput = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [options, setOptions] = useState<Options>(defaults);
  const [formError, setFormError] = useState('');
  const id = useId();
  const { config, uploads, jobs, error, submitting, addFiles, removeUpload, submit, changeJob } = useWorkbench(tool);
  useEffect(() => {
    setOptions((current) => {
      const languages = (current.languages as string[]).filter((language) => config.ocr_languages.includes(language));
      return { ...current, languages: languages.length ? languages : config.ocr_languages.slice(0, 1) };
    });
  }, [config.ocr_languages]);
  const records = uploads.flatMap((upload) => upload.record ? [upload.record] : []);
  const uploading = uploads.some((upload) => !upload.record && !upload.error);
  const batchIds = [...new Set(jobs.flatMap(({ batch_id }) => batch_id ? [batch_id] : []))];
  const finishedBatches = batchIds.filter((batchId) => {
    const batchJobs = jobs.filter(({ batch_id }) => batchId === batch_id);
    return batchJobs.some(({ status }) => status === 'completed') && !batchJobs.some(isActive);
  });
  const name = tool.accept === '.pdf' ? 'PDF' : tool.accept === '.docx' ? 'DOCX' : 'JPG';
  const haveEnough = tool.id === 'merge-pdf' ? records.length > 1 : records.length > 0;

  async function createJob(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!haveEnough || uploading || submitting) return;
    setFormError('');
    try {
      const settings = makeSettings(tool.id, options, records);
      if (await submit(settings)) setOptions({ ...options, password: '' });
    } catch (caught) { setFormError(errorText(caught)); }
  }

  return <div className={`workbench ${compact ? 'workbench-compact' : ''}`}>
    <div className={`dropzone${dragging ? ' dropzone-active' : ''}`} aria-describedby={`${id}-limits`}
      onDragOver={(event) => { event.preventDefault(); if (event.dataTransfer.types.includes('Files')) setDragging(true); }}
      onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false); }}
      onDrop={(event) => { event.preventDefault(); setDragging(false); setFormError(''); addFiles(Array.from(event.dataTransfer.files)); }}>
      <div className="drop-icon"><CloudUpload size={25} strokeWidth={1.9} aria-hidden="true" /></div>
      <p>Drag and drop your {name} files</p>
      <input type="file" accept={tool.accept} multiple ref={fileInput} hidden onChange={(event) => {
        setFormError('');
        addFiles(Array.from(event.target.files ?? []));
        event.target.value = '';
      }} />
      <Button onClick={() => fileInput.current?.click()} className="choose-button" aria-describedby={`${id}-limits`}><Upload size={17} aria-hidden="true" /> Choose {name} files</Button>
      <small id={`${id}-limits`}>Up to {config.max_batch_files} files · {config.max_upload_mb} MB each</small>
    </div>
    {!uploads.length && !jobs.length && <p className="upload-privacy"><LockKeyhole size={14} strokeWidth={2.1} aria-hidden="true" /> Private uploads · Files expire after {config.retention_minutes} minutes</p>}
    {(error || formError) && <p className="inline-error" role="alert"><CircleAlert size={18} aria-hidden="true" />{formError || error}</p>}
    {!!uploads.length && <form className="work-panel" onSubmit={(event) => void createJob(event)}>
      <h2 className="work-title">Selected files <span>{uploads.length}</span></h2>
      {isCombined(tool) && <p className="muted">Files are combined in the order shown.</p>}
      <ul className="upload-list">
        {uploads.map((upload) => <li key={upload.key} className="upload-row">
          <span className="file-icon">{!upload.record && !upload.error ? <LoaderCircle size={19} className="spinner" aria-hidden="true" /> : <FileText size={19} aria-hidden="true" />}</span>
          <div className="file-info">
            <strong title={upload.record?.original_filename || upload.file.name}>{upload.record?.original_filename || upload.file.name}</strong>
            <small>{fileSize(upload.file.size)}{upload.record?.page_count ? ` · ${upload.record.page_count} ${upload.record.page_count === 1 ? 'page' : 'pages'}` : ''}{upload.record?.encrypted ? ' · Password protected' : ''}{!upload.record && !upload.error ? ' · Uploading' : ''}</small>
            {upload.error && <p className="inline-error">{upload.error}</p>}
          </div>
          <button className="icon-button file-action" type="button" disabled={submitting || (!upload.record && !upload.error)} aria-label={`Remove ${upload.file.name}`} onClick={() => void removeUpload(upload)}><X size={18} aria-hidden="true" /></button>
        </li>)}
      </ul>
      <ConversionSettings tool={tool.id} records={records} config={config} options={options} onChange={setOptions} />
      <div className="work-actions">
        <span className="muted">{tool.id === 'pdf-to-word' ? 'Output · DOCX' : tool.id === 'merge-pdf' && records.length < 2 ? 'Select at least two PDFs' : ''}</span>
        <Button type="submit" disabled={uploading || submitting || !haveEnough}>{submitting && <LoaderCircle size={17} className="spinner" aria-hidden="true" />}{tool.action}</Button>
      </div>
    </form>}
    {!!jobs.length && <section className="work-panel" aria-labelledby={`${id}-results`}>
      <div className="work-head"><h2 className="work-title" id={`${id}-results`}>Results</h2>
        {!!finishedBatches.length && <div className="batch-downloads">{finishedBatches.map((batchId, index) => <a key={batchId} className={buttonClass('outline', 'action-button')} href={batchUrl(batchId)} download><Archive size={17} aria-hidden="true" /> Download batch{finishedBatches.length > 1 ? ` ${index + 1}` : ''} ZIP</a>)}</div>}
      </div>
      <div className="job-list" aria-live="polite">{jobs.map((job) => <JobRow key={job.id} job={job} change={changeJob} />)}</div>
    </section>}
  </div>;
}
