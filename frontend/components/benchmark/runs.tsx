'use client';

import { useState, type FormEvent, type ReactNode } from 'react';
import { Activity, Boxes, ChevronDown, Clock3, Database, FileDown, FileText, Gauge, Play, RefreshCw, ShieldCheck } from 'lucide-react';
import { errorText, json } from '@/lib/api';
import { active, createRun, fetchBench, formatTime, label, metric, object, percent, points, reportUrl, runPath, seconds, type BenchmarkConfiguration, type BenchmarkRun, type CaseResult, type Dataset, type DatasetCase, type RunDetail, type RunRequest } from '@/lib/benchmarks';
import { Button, buttonClass } from '@/components/ui/button';
import { Bar, Empty, ErrorNotice, Facts, NoticeList, Panel, Status, scalar } from './common';

const thresholdLabels: Record<string, string> = {
  tables_score: 'Table preservation', images_score: 'Image preservation', docx_valid: 'DOCX validity', cleanup_rate: 'Temporary cleanup',
};

type SelectRun = (id: string) => void;

export function Overview({ run, runs, openRun, openExecution, openDatasets, openHistory }: {
  run?: BenchmarkRun;
  runs: BenchmarkRun[];
  openRun: SelectRun;
  openExecution: () => void;
  openDatasets: () => void;
  openHistory: () => void;
}) {
  const finished = run?.summary ? run : runs.find((entry) => entry.summary);
  const summary = object(finished?.summary);
  const aggregate = object(summary.metrics);
  const scores = Object.entries(object(summary.category_scores));
  const hasScore = metric(summary.overall_score) !== undefined;
  const base = object(summary.baseline);
  const delta = metric(base.delta);
  const coverage = metric(summary.coverage_weight);
  const stats: [string, ReactNode, typeof Activity][] = [
    ['PDFs tested', scalar(summary.total), FileText],
    ['Conversion success', percent(summary.conversion_success_rate), Activity],
    ['Text accuracy', percent(aggregate.text_accuracy), FileText],
    ['Layout similarity', percent(aggregate.layout_similarity), Boxes],
    ['OCR accuracy', percent(aggregate.ocr_accuracy), Gauge],
    ['DOCX validity', percent(aggregate.docx_valid), ShieldCheck],
    ['Mean conversion time', seconds(summary.mean_duration_seconds), Clock3],
    ['Failed quality gates', scalar(summary.failed_cases), Activity],
  ];

  return <div className="bench-stack">
    {finished ? <>
      <section className="bench-overview-score">
        <div>
          <div className="bench-score-label"><Gauge size={19} aria-hidden="true" /> Overall benchmark score</div>
          <p className="bench-score-value">{points(summary.overall_score)}{hasScore && <span> / 100</span>}</p>
          <div className="bench-score-meta">
            <span>{finished.name || 'Benchmark run'}</span><span>{coverage === undefined ? `Dataset v${finished.dataset_version}` : `${coverage} weighted points measured`}</span>
          </div>
        </div>
        <div className="bench-score-side">
          <Status value={finished.status} />
          {delta !== undefined && <p className="bench-delta">{delta > 0 ? '+' : ''}{delta.toFixed(1)} points vs previous comparable run</p>}
          <time dateTime={finished.finished_at ?? finished.created_at}>{formatTime(finished.finished_at ?? finished.created_at)}</time>
        </div>
      </section>
      <div className="bench-stat-grid">{stats.map(([key, value, Icon]) => <article className="bench-stat" key={key}>
        <span className="bench-stat-icon"><Icon size={17} aria-hidden="true" /></span>
        <span className="bench-stat-label">{key}</span><strong>{value}</strong>
      </article>)}</div>
      {scores.length > 0 && <Panel title="Category scores" description="Scores are based on available evidence for this run.">
        <div className="bench-category-grid">{scores.map(([key, value]) => <div className="bench-category" key={key}>
          <div><span>{label(key)}</span><strong>{points(value)}{metric(value) !== undefined && <small> / 100</small>}</strong></div>
          {metric(value) !== undefined && <Bar value={Number(value)} max={100} />}
        </div>)}</div>
      </Panel>}
      {!!arrayOfStrings(summary.recommendations).length && <Panel title="Improvement priorities">
        <NoticeList title="Recommendations from measured failures" items={arrayOfStrings(summary.recommendations)} />
      </Panel>}
    </> : <Panel title="Conversion quality">
      <Empty title="No completed benchmark yet" action={<div className="bench-actions">
        <Button onClick={openExecution}><Play size={16} aria-hidden="true" /> Run benchmark</Button>
        <Button variant="outline" onClick={openDatasets}><Database size={16} aria-hidden="true" /> Manage datasets</Button>
      </div>}>Prepare a dataset and run the converter to measure text accuracy, layout, and document compatibility.</Empty>
    </Panel>}
    <Panel title="Recent runs" action={<Button variant="ghost" onClick={openHistory}>View run history</Button>}>
      <RunTable runs={runs.slice(0, 6)} onSelect={openRun} />
    </Panel>
  </div>;
}

function arrayOfStrings(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function RunTable({ runs, onSelect }: { runs: BenchmarkRun[]; onSelect: SelectRun }) {
  if (!runs.length) return <Empty title="No runs to show" />;
  return <div className="bench-table-scroll"><table className="bench-table">
    <thead><tr><th scope="col">Run</th><th scope="col">Dataset revision</th><th scope="col">Status</th><th scope="col">Progress</th><th scope="col">Score</th><th scope="col">Started</th></tr></thead>
    <tbody>{runs.map((run) => <tr key={run.id}>
      <th scope="row"><button className="bench-text-button" onClick={() => onSelect(run.id)}>{run.name || run.id}</button></th>
      <td>{run.dataset_name ? `${run.dataset_name} · ` : ''}v{run.dataset_version}</td>
      <td><Status value={run.status} /></td>
      <td>{run.completed} / {run.total}</td>
      <td>{points(run.summary?.overall_score)}</td>
      <td><time dateTime={run.created_at}>{formatTime(run.created_at)}</time></td>
    </tr>)}</tbody>
  </table></div>;
}

export function History({ runs, onSelect }: { runs: BenchmarkRun[]; onSelect: SelectRun }) {
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const filtered = runs.filter((item) => (!status || item.status === status) && `${item.name} ${item.dataset_name ?? ''} ${item.dataset_version}`.toLowerCase().includes(search.toLowerCase()));
  return <Panel title="Run history" description="Open a run to inspect its configuration, results, and reports.">
    <div className="bench-filters">
      <input className="field-input" type="search" aria-label="Search benchmark runs" placeholder="Search run name or dataset" value={search} onChange={(event) => setSearch(event.target.value)} />
      <select className="field-input" aria-label="Filter run status" value={status} onChange={(event) => setStatus(event.target.value)}>
        <option value="">All statuses</option>{[...new Set(runs.map((item) => item.status))].map((value) => <option key={value} value={value}>{label(value)}</option>)}
      </select>
    </div>
    <RunTable runs={filtered} onSelect={onSelect} />
  </Panel>;
}

export function RunForm({ datasets, datasetId, cases, initialCaseIds, config, onDataset, onRun }: {
  datasets: Dataset[];
  datasetId: string;
  cases: DatasetCase[];
  initialCaseIds: string;
  config: BenchmarkConfiguration;
  onDataset: (id: string) => void;
  onRun: (run: BenchmarkRun) => void;
}) {
  const ready = datasets.filter((dataset) => dataset.status === 'ready' && dataset.case_count > 0);
  const rates = Object.entries(config.thresholds).filter(([key]) => key !== 'target_seconds');
  const selectedId = ready.some((dataset) => dataset.id === datasetId) ? datasetId : '';
  const categories = [...new Set(cases.map((entry) => entry.category))].sort();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError('');
    setBusy(true);
    try {
      const selectedCases = String(form.get('case_ids') || '').split(/[\s,]+/).filter(Boolean);
      const weights = Object.fromEntries(Object.keys(config.weights).map((key) => [key, Number(form.get(`weight:${key}`))]));
      if (Math.abs(Object.values(weights).reduce((total, value) => total + value, 0) - 100) > 0.00001) {
        throw new Error('Category weights must add up to 100.');
      }
      const thresholds = Object.fromEntries(rates.map(([key]) => [key, Number(form.get(`threshold:${key}`)) / 100]));
      thresholds.target_seconds = Number(form.get('target_seconds'));
      const request: RunRequest = {
        dataset_id: selectedId,
        name: String(form.get('name')).trim() || 'Conversion benchmark',
        weights,
        thresholds,
        max_visual_pages: Number(form.get('max_visual_pages')),
        timeout_seconds: Number(form.get('timeout_seconds')),
      };
      const requestedCategory = String(form.get('category') || '');
      if (requestedCategory) request.category = requestedCategory;
      if (selectedCases.length) request.case_ids = [...new Set(selectedCases)];
      const mode = String(form.get('mode') || '');
      const ocr = String(form.get('ocr') || '');
      const languages = String(form.get('languages') || '').split(/[\s,]+/).filter(Boolean);
      if (mode || ocr || languages.length) request.settings = {
        ...(mode ? { mode } : {}), ...(ocr ? { ocr } : {}), ...(languages.length ? { languages } : {}),
      };
      onRun(await createRun(request));
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  return <Panel title="Run a benchmark" description="Use an entire revision, a category, or a list of case IDs.">
    {!ready.length ? <Empty title="A populated dataset is required">Generate the synthetic corpus or upload test cases to a dataset revision.</Empty> :
      <form className="bench-form" onSubmit={(event) => void submit(event)}>
        <div className="bench-form-grid">
          <label>Run name<input className="field-input" name="name" placeholder="November quality regression" maxLength={100} /></label>
          <label>Dataset revision<select className="field-input" required value={selectedId} onChange={(event) => onDataset(event.target.value)}>
            <option value="">Select a dataset</option>{ready.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name} · v{dataset.version} · {dataset.case_count} cases</option>)}
          </select></label>
          <label>Category<select key={datasetId} className="field-input" name="category"><option value="">All categories</option>
            {categories.map((category) => <option value={category} key={category}>{label(category)}</option>)}
          </select></label>
          <label>Case IDs (optional)<input key={`${datasetId}:${initialCaseIds}`} className="field-input" name="case_ids" placeholder="PDF-001, PDF-015, PDF-030" defaultValue={initialCaseIds} /></label>
        </div>
        <details className="bench-action-details">
          <summary>Conversion and scoring settings <ChevronDown size={16} aria-hidden="true" /></summary>
          <div className="bench-details-inner">
            <div className="bench-form-grid">
              <label>Conversion mode<select className="field-input" name="mode"><option value="">Use case settings</option><option value="editable">Editable layout</option><option value="flowing">Flowing text</option><option value="visual">Visual pages</option></select></label>
              <label>OCR preference<select className="field-input" name="ocr"><option value="">Use case settings</option><option value="auto">Automatic detection</option><option value="force">Force OCR</option><option value="off">Disable OCR</option></select></label>
              <label>OCR languages (optional)<input className="field-input" name="languages" placeholder="eng, urd, ara" /></label>
              <label>Maximum visual pages per case<input className="field-input" name="max_visual_pages" type="number" min={1} max={config.max_visual_pages} step={1} defaultValue={Math.min(8, config.max_visual_pages)} required /></label>
              <label>Per-case timeout (seconds)<input className="field-input" name="timeout_seconds" type="number" min={15} max={240} step={1} defaultValue={120} required /></label>
            </div>
            <fieldset className="bench-fieldset"><legend>Category weights</legend>
              <p className="bench-muted">Weights must total 100 points.</p>
              <div className="bench-form-grid bench-form-grid-three">
                {Object.entries(config.weights).map(([key, value]) => <label key={key}>{label(key)}<input className="field-input" type="number" name={`weight:${key}`} defaultValue={value} min={0} max={100} step="any" required /></label>)}
              </div>
            </fieldset>
            <fieldset className="bench-fieldset"><legend>Quality thresholds</legend>
              <p className="bench-muted">Rates are percentages. Duration is per document in seconds.</p>
              <div className="bench-form-grid bench-form-grid-three">
                {rates.map(([key, value]) => <label key={key}>{thresholdLabels[key] ?? label(key)}<input className="field-input" type="number" name={`threshold:${key}`} defaultValue={Math.round(value * 10000) / 100} min={0} max={100} step="any" required /></label>)}
                <label>Target conversion duration<input className="field-input" type="number" name="target_seconds" defaultValue={config.thresholds.target_seconds} max={3600} min={.1} step="any" required /></label>
              </div>
            </fieldset>
          </div>
        </details>
        <ErrorNotice>{error}</ErrorNotice>
        <Button type="submit" disabled={!selectedId || busy}><Play size={17} aria-hidden="true" />{busy ? 'Starting…' : 'Start benchmark'}</Button>
      </form>}
  </Panel>;
}

export function RunProgress({ run, onRun, onCompare }: { run: RunDetail; onRun: (run: BenchmarkRun) => void; onCompare: (caseId: string) => void }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const failed = run.results.some((entry) => entry.passed === false || entry.status === 'failed');
  const inProgress = active(run.status);
  const score = object(run.summary);

  async function rerun() {
    setBusy(true);
    setError('');
    try {
      onRun(await fetchBench<BenchmarkRun>(`${runPath(run.id)}/rerun`, json('POST')));
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  return <Panel title={run.name || 'Benchmark run'} description={`Dataset v${run.dataset_version} · Started ${formatTime(run.created_at)}`}
    action={<><Status value={run.status} />{failed && !inProgress && <Button variant="outline" onClick={() => void rerun()} disabled={busy}><RefreshCw size={16} aria-hidden="true" />{busy ? 'Requesting…' : 'Rerun failed cases'}</Button>}</>}>
    <ErrorNotice>{error || run.error}</ErrorNotice>
    <div className="bench-progress" role="status">
      <div><span>{run.completed} of {run.total} cases finished</span><strong>{score.overall_score == null ? `${Math.round(100 * run.completed / Math.max(run.total, 1))}%` : `${points(score.overall_score)} / 100`}</strong></div>
      <Bar value={run.completed} max={run.total} />
    </div>
    <Facts entries={[
      ['Run ID', <code className="bench-hash">{run.id}</code>],
      ['Application version', run.application_version || '—'],
      ...(run.dataset_sha256 ? [['Dataset manifest SHA-256', <code className="bench-hash">{run.dataset_sha256}</code>] as [string, ReactNode]] : []),
      ['Failed cases', run.failed],
      ['Finished', formatTime(run.finished_at)],
    ]} />
    {!!run.configuration && <details className="bench-action-details"><summary>Recorded configuration</summary><pre className="bench-code">{JSON.stringify(run.configuration, null, 2)}</pre></details>}
    <ResultTable results={run.results} select={onCompare} />
  </Panel>;
}

export function ResultTable({ results, select }: { results: CaseResult[]; select: (caseId: string) => void }) {
  if (!results.length) return <Empty title="No case results yet" />;
  return <div className="bench-table-scroll bench-result-table"><table className="bench-table">
    <thead><tr><th scope="col">Case</th><th scope="col">Category</th><th scope="col">Status</th><th scope="col">Score</th><th scope="col">Conversion</th><th scope="col">Message</th></tr></thead>
    <tbody>{results.map((entry) => <tr key={entry.case_id}>
      <th scope="row"><button className="bench-text-button" onClick={() => select(entry.case_id)}>{entry.case_id}</button></th>
      <td>{label(entry.category)}</td><td><Status value={entry.status} passed={entry.passed} /></td><td>{points(entry.score)}</td>
      <td>{seconds(entry.duration_seconds)}</td><td>{entry.error || '—'}</td>
    </tr>)}</tbody>
  </table></div>;
}

export function Reports({ run }: { run?: RunDetail }) {
  return <Panel title="Benchmark reports" description="Export the selected run and its measured diagnostics.">
    {!run || active(run.status) || !run.summary ? <Empty title="Select a completed run to export" /> : <>
      <Facts entries={[
        ['Run', run.name], ['Dataset revision', run.dataset_version], ['Completed', formatTime(run.finished_at)],
        ['Overall score', points(run.summary.overall_score)], ['Reference cases compared', scalar(run.summary.references_compared)],
      ]} />
      <div className="bench-format-grid">{[
        ['PDF', 'Printable summary'], ['HTML', 'Diagnostic report'], ['JSON', 'Machine-readable results'], ['CSV', 'Case metrics'],
      ].map(([format, description]) => <a download href={reportUrl(run.id, format.toLowerCase())} key={format} className="bench-format">
        <FileDown size={23} aria-hidden="true" /><span><strong>{format}</strong><small>{description}</small></span>
      </a>)}</div>
    </>}
  </Panel>;
}
