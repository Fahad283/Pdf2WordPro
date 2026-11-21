import type { ToolId } from './tools';

const prefix = '/api/v1';

export type FileRecord = {
  id: string;
  original_filename: string;
  size_bytes: number;
  page_count: number | null;
  mime_type: string;
  encrypted: boolean;
  created_at: string;
  expires_at: string;
};

export type Job = {
  id: string;
  batch_id: string | null;
  tool: ToolId;
  input_files: FileRecord[];
  status: 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  error: string | null;
  warnings: string[];
  metrics: Record<string, unknown>;
  created_at: string;
  expires_at: string;
  output_filename: string | null;
};

export type Config = {
  max_upload_mb: number;
  max_pages: number;
  max_batch_files: number;
  retention_minutes: number;
  ocr_languages: string[];
  daily_conversion_limit: number;
};

export type User = {
  id: string;
  email: string;
  role: 'user' | 'admin';
  plan: 'free' | 'premium';
  status: 'active' | 'suspended';
};

export type Metrics = {
  total_users: number;
  total_uploads: number;
  total_conversions: number;
  successful_conversions: number;
  failed_conversions: number;
  active_jobs: number;
  queue_status: string;
  average_conversion_seconds: number | null;
  storage_bytes: number;
  ocr_jobs: number;
  system_health: string;
  recent_errors: { id: string; tool: ToolId; error: string; created_at: string }[];
};

export const fallbackConfig: Config = {
  max_upload_mb: 50, max_pages: 500, max_batch_files: 10, retention_minutes: 60,
  ocr_languages: ['eng', 'urd', 'ara'], daily_conversion_limit: 40,
};

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${prefix}${path}`, { cache: 'no-store', ...options });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    const message = typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map(({ msg }: { msg?: string }) => msg).filter(Boolean).join(' ')
      : '';
    throw new ApiError(message || `The service returned an error (${response.status}).`, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function json(method: 'POST' | 'PATCH', body: object = {}): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

export function jobUrl(id: string, action?: 'events' | 'download') {
  return `${prefix}/conversions/${encodeURIComponent(id)}${action ? `/${action}` : ''}`;
}

export function batchUrl(id: string) {
  return `${prefix}/conversions/batches/${encodeURIComponent(id)}/download`;
}

export function isActive(job: Job) {
  return job.status === 'queued' || job.status === 'processing';
}

export function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'An unexpected error occurred.';
}
