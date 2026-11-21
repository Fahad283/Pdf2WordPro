'use client';

import { useEffect, useRef, useState } from 'react';
import { api, errorText, fallbackConfig, isActive, jobUrl, json, type Config, type FileRecord, type Job } from '@/lib/api';
import { isCombined, type Tool } from '@/lib/tools';

export type Upload = { key: string; file: File; record?: FileRecord; error?: string };

export function useWorkbench(tool: Tool) {
  const [config, setConfig] = useState(fallbackConfig);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const pendingUploads = useRef(Promise.resolve());
  const uploadsRef = useRef<Upload[]>([]);
  const watchers = useRef(new Map<string, () => void>());

  useEffect(() => {
    const activeWatchers = watchers.current;
    const controller = new AbortController();
    pendingUploads.current = api<Config>('/config', { signal: controller.signal }).then(setConfig).catch(() => {});
    return () => {
      controller.abort();
      activeWatchers.forEach((stop) => stop());
      activeWatchers.clear();
    };
  }, []);

  function updateUploads(update: (items: Upload[]) => Upload[]) {
    const next = update(uploadsRef.current);
    uploadsRef.current = next;
    setUploads(next);
  }

  function addFiles(newFiles: File[]) {
    setError('');
    const accepted: Upload[] = [];
    const errors: string[] = [];
    const suffixes = tool.accept.split(',');
    for (const file of newFiles) {
      if (!suffixes.some((suffix) => file.name.toLowerCase().endsWith(suffix))) {
        errors.push(`${file.name} has a file type this tool cannot process.`);
      } else if (file.size > config.max_upload_mb * 1024 * 1024) {
        errors.push(`${file.name} exceeds the ${config.max_upload_mb} MB limit.`);
      } else if (uploadsRef.current.length + accepted.length >= config.max_batch_files) {
        errors.push(`You can upload up to ${config.max_batch_files} files at a time.`);
        break;
      } else {
        accepted.push({ key: crypto.randomUUID(), file });
      }
    }
    if (errors.length) setError(errors.join(' '));
    if (!accepted.length) return;
    updateUploads((items) => [...items, ...accepted]);
    // The first completed upload can establish the guest session. Keep cookie creation ordered.
    pendingUploads.current = pendingUploads.current.then(async () => {
      for (const entry of accepted) {
        const body = new FormData();
        body.append('file', entry.file);
        let result: Partial<Upload>;
        try { result = { record: await api<FileRecord>('/files/upload', { method: 'POST', body }) }; }
        catch (caught) { result = { error: errorText(caught) }; }
        updateUploads((items) => items.map((item) => item.key === entry.key ? { ...item, ...result } : item));
      }
    });
  }

  async function removeUpload(upload: Upload) {
    setError('');
    try {
      if (upload.record) await api(`/files/${upload.record.id}`, { method: 'DELETE' });
      updateUploads((items) => items.filter((item) => item.key !== upload.key));
    } catch (caught) { setError(errorText(caught)); }
  }

  function updateJob(job: Job) {
    setJobs((current) => current.some(({ id }) => id === job.id)
      ? current.map((previous) => previous.id === job.id ? job : previous)
      : [...current, job]);
  }

  function watch(job: Job) {
    watchers.current.get(job.id)?.();
    if (!isActive(job)) return;
    const eventSource = new EventSource(jobUrl(job.id, 'events'));
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const stop = () => {
      active = false;
      eventSource.close();
      if (timer) clearTimeout(timer);
      watchers.current.delete(job.id);
    };
    watchers.current.set(job.id, stop);
    function receive(next: Job) {
      if (!active) return;
      updateJob(next);
      if (!isActive(next)) stop();
    }
    async function poll() {
      try { receive(await api<Job>(`/conversions/${job.id}`)); }
      catch { /* A temporary network error can recover on the next request. */ }
      if (active) timer = setTimeout(poll, 2500);
    }
    eventSource.addEventListener('status', (event: MessageEvent<string>) => {
      try { receive(JSON.parse(event.data) as Job); }
      catch { /* Keep listening if a malformed event is received. */ }
    });
    eventSource.onerror = () => { eventSource.close(); if (active) void poll(); };
  }

  async function submit(settings: Record<string, unknown>) {
    const fileIds = uploads.flatMap((item) => item.record ? [item.record.id] : []);
    if (!fileIds.length) return false;
    setSubmitting(true);
    setError('');
    try {
      const body = { tool: tool.id, file_ids: fileIds, settings };
      if (fileIds.length > 1 && !isCombined(tool)) {
        const result = await api<{ id: string; jobs: Job[] }>('/conversions/batch', json('POST', body));
        result.jobs.forEach((job) => { updateJob(job); watch(job); });
      } else {
        const result = await api<Job>('/conversions', json('POST', body));
        updateJob(result);
        watch(result);
      }
      updateUploads((items) => items.filter((item) => !item.record || !fileIds.includes(item.record.id)));
      return true;
    } catch (caught) {
      setError(errorText(caught));
      return false;
    } finally { setSubmitting(false); }
  }

  async function changeJob(id: string, action: 'retry' | 'cancel' | 'delete', password?: string) {
    setError('');
    try {
      if (action === 'delete') {
        await api(`/conversions/${id}`, { method: 'DELETE' });
        watchers.current.get(id)?.();
        setJobs((current) => current.filter((job) => job.id !== id));
      } else {
        const next = await api<Job>(`/conversions/${id}/${action}`, json('POST', password ? { password } : {}));
        if (action === 'retry' && next.id !== id) setJobs((current) => current.filter((job) => job.id !== id));
        updateJob(next);
        watch(next);
      }
    } catch (caught) { setError(errorText(caught)); }
  }

  return { config, uploads, jobs, error, submitting, addFiles, removeUpload, submit, changeJob };
}
