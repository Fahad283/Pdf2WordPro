import { api, json } from './api';

export const benchmarkPath = '/benchmarks';
const prefix = '/api/v1' + benchmarkPath;

export type MetricsRecord = Record<string, unknown>;

export type Dataset = {
  id: string;
  name: string;
  version: string;
  status: string;
  case_count: number;
  created_at: string;
  error?: string | null;
  locked: boolean;
  manifest_sha256?: string | null;
};

export type DatasetCase = {
  id: string;
  case_id: string;
  category: string;
  description: string;
  behavior: string;
  sha256: string;
  size_bytes: number;
  settings: MetricsRecord;
  has_reference: boolean;
  expected_error?: string | null;
};

export type GroundTruthPage = {
  text?: string;
  width?: number;
  height?: number;
  tables?: unknown[][][];
  images?: unknown[];
  blocks?: unknown[];
};

export type GroundTruth = {
  pages?: GroundTruthPage[];
  features?: Record<string, number>;
  languages?: string[];
  ocr_required?: boolean;
};

export type Reference = {
  provider?: string;
  duration_seconds?: number | null;
  notes?: string | null;
  source_sha256?: string;
  sha256?: string;
  size_bytes?: number;
  created_at?: string;
  download_url?: string;
};

export type CaseDetail = DatasetCase & {
  ground_truth: GroundTruth;
  reference?: Reference | null;
  source_url?: string;
  reference_url?: string;
  assets?: Record<string, string>;
};

export type DatasetDetail = Dataset & { cases: DatasetCase[] };

export type BenchmarkRun = {
  id: string;
  name: string;
  dataset_id: string;
  dataset_name?: string;
  dataset_version: string;
  status: string;
  total: number;
  completed: number;
  failed: number;
  created_at: string;
  finished_at?: string | null;
  application_version?: string;
  dataset_sha256?: string;
  error?: string | null;
  summary?: MetricsRecord | null;
  configuration?: MetricsRecord;
  parent_id?: string | null;
};

export type CaseResult = {
  case_id: string;
  category: string;
  status: string;
  passed: boolean | null;
  score: number | null;
  duration_seconds: number | null;
  error: string | null;
  metrics: MetricsRecord;
};

export type RunDetail = BenchmarkRun & { results: CaseResult[] };

export type PageDiagnostic = MetricsRecord & {
  page?: number;
  source_page?: number;
  rendered_page?: number | null;
  artifacts?: Record<string, string>;
  warnings?: string[];
};

export type ResultDetail = CaseResult & {
  details?: {
    metrics?: MetricsRecord;
    pages?: PageDiagnostic[];
    extracted?: Record<string, string>;
    structure?: MetricsRecord;
    features?: MetricsRecord;
    languages?: MetricsRecord;
    tables?: unknown[];
    warnings?: string[];
    critical?: string[];
    artifacts?: Record<string, string>;
    reference?: (Reference & {
      metrics?: MetricsRecord;
      pages?: PageDiagnostic[];
      extracted?: Record<string, string>;
      warnings?: string[];
      critical?: string[];
      artifacts?: Record<string, string>;
      tables?: unknown[];
      error?: string;
    }) | null;
  };
  assets?: Record<string, string>;
  artifact_urls?: Record<string, string>;
};

export type RunRequest = {
  dataset_id: string;
  name: string;
  category?: string;
  case_ids?: string[];
  settings?: MetricsRecord;
  weights?: Record<string, number>;
  thresholds?: Record<string, number>;
  max_visual_pages?: number;
  timeout_seconds?: number;
};

export type BenchmarkConfiguration = {
  weights: Record<string, number>;
  thresholds: Record<string, number>;
  max_visual_pages: number;
  max_dataset_cases: number;
  benchmark_version: string;
};

export const encode = encodeURIComponent;

export function fetchBench<T>(path: string, options?: RequestInit) {
  return api<T>(benchmarkPath + path, options);
}

export function createRun(values: RunRequest) {
  return fetchBench<BenchmarkRun>('/runs', json('POST', values));
}

export function datasetPath(id: string) {
  return `/datasets/${encode(id)}`;
}

export function casePath(dataset: string, caseId: string) {
  return `${datasetPath(dataset)}/cases/${encode(caseId)}`;
}

export function runPath(id: string) {
  return `/runs/${encode(id)}`;
}

export function resultPath(run: string, caseId: string) {
  return `${runPath(run)}/results/${encode(caseId)}`;
}

export function reportUrl(run: string, format: string) {
  return `${prefix}${runPath(run)}/reports/${encode(format)}`;
}

export function safeAssetUrl(value?: string | null) {
  return value?.startsWith(`${prefix}/`) ? value : undefined;
}

export function active(status?: string) {
  return status === 'building' || status === 'queued' || status === 'running' || status === 'processing';
}

export function metric(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

export function object(value: unknown): MetricsRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as MetricsRecord : {};
}

export function percent(value: unknown) {
  const number = metric(value);
  return number === undefined ? '—' : `${(number * 100).toFixed(1)}%`;
}

export function points(value: unknown) {
  const number = metric(value);
  return number === undefined ? '—' : number.toFixed(1);
}

export function seconds(value: unknown) {
  const number = metric(value);
  return number === undefined ? '—' : `${number.toFixed(number < 1 ? 3 : 2)} s`;
}

export function label(value: string) {
  const acronyms: Record<string, string> = { ocr: 'OCR', docx: 'DOCX', pdf: 'PDF', rtl: 'RTL', cer: 'CER', wer: 'WER', ssim: 'SSIM', cpu: 'CPU', rss: 'RSS', dpi: 'DPI' };
  const words = value.replace(/[_-]/g, ' ').split(' ');
  return words.map((word, index) => acronyms[word.toLowerCase()] ?? (index === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word)).join(' ');
}

export function formatTime(value?: string | null) {
  if (!value) return '—';
  const date = new Date(/(?:Z|[+-]\d\d:\d\d)$/i.test(value) ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}
