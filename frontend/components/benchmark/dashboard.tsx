'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Activity, ChartNoAxesColumn, Database, FileDown, Files, Gauge, History as HistoryIcon, LockKeyhole, Play, RefreshCw, ScanText, ShieldCheck, TriangleAlert } from 'lucide-react';
import { ApiError, errorText } from '@/lib/api';
import { active, casePath, datasetPath, fetchBench, label, resultPath, runPath, type BenchmarkConfiguration, type BenchmarkRun, type CaseDetail, type Dataset, type DatasetDetail, type ResultDetail, type RunDetail } from '@/lib/benchmarks';
import { Button, buttonClass } from '@/components/ui/button';
import { Empty, ErrorNotice, Loading } from './common';
import { DatasetsView } from './datasets';
import { Comparison, Failures, OCRAnalysis, Performance, Security } from './diagnostics';
import { History, Overview, Reports, RunForm, RunProgress } from './runs';

const views = [
  ['overview', 'Overview', Gauge],
  ['datasets', 'Datasets', Database],
  ['execute', 'Run benchmark', Play],
  ['history', 'Run history', HistoryIcon],
  ['compare', 'Comparison', Files],
  ['ocr', 'OCR analysis', ScanText],
  ['performance', 'Performance', Activity],
  ['security', 'Security', ShieldCheck],
  ['failures', 'Failures', TriangleAlert],
  ['reports', 'Reports', FileDown],
] as const;

type View = typeof views[number][0];

type Index = {
  datasets: Dataset[];
  runs: BenchmarkRun[];
  config?: BenchmarkConfiguration;
  loading: boolean;
  error?: string;
  denied?: boolean;
};

const runViews: View[] = ['execute', 'compare', 'ocr', 'performance', 'security', 'failures', 'reports'];

function useIndex(revision: number) {
  const [data, setData] = useState<Index>({ datasets: [], runs: [], loading: true });

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let polling = false;
    async function load() {
      try {
        const [datasets, runs, config] = await Promise.all([
          fetchBench<{ datasets: Dataset[] }>('/datasets', { signal: controller.signal }),
          fetchBench<{ runs: BenchmarkRun[] }>('/runs', { signal: controller.signal }),
          fetchBench<BenchmarkConfiguration>('/configuration', { signal: controller.signal }),
        ]);
        if (controller.signal.aborted) return;
        const datasetNames = new Map(datasets.datasets.map((item) => [item.id, item.name]));
        setData({ datasets: datasets.datasets, runs: runs.runs.map((item) => ({ ...item, dataset_name: datasetNames.get(item.dataset_id) })), config, loading: false });
        polling = [...datasets.datasets, ...runs.runs].some((item) => active(item.status));
      } catch (caught) {
        if (controller.signal.aborted) return;
        const denied = caught instanceof ApiError && (caught.status === 401 || caught.status === 403);
        setData((current) => ({ ...current, loading: false, error: errorText(caught), denied }));
        if (denied) polling = false;
      }
      if (polling) timer = setTimeout(load, 2500);
    }
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [revision]);

  return data;
}

function useResource<T>(path: string | null, revision: number, poll: boolean) {
  const [state, setState] = useState<{ path: string; value?: T; error?: string }>();
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const value = await fetchBench<T>(path!, { signal: controller.signal });
        if (!controller.signal.aborted) setState({ path: path!, value });
      } catch (caught) {
        if (!controller.signal.aborted) setState((current) => ({ path: path!, value: current?.path === path ? current.value : undefined, error: errorText(caught) }));
      }
      if (poll && !controller.signal.aborted) timer = setTimeout(load, 2300);
    }
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [path, poll, revision]);

  return {
    value: state?.path === path ? state?.value : undefined,
    error: state?.path === path ? state?.error : undefined,
    loading: Boolean(path && state?.path !== path),
  };
}

export function BenchmarkDashboard() {
  const router = useRouter();
  const search = useSearchParams();
  const currentView = search.get('view');
  const view = views.find(([key]) => key === currentView)?.[0] ?? 'overview';
  const [revision, setRevision] = useState(0);
  const index = useIndex(revision);
  const datasetId = search.get('dataset') || index.datasets[0]?.id || '';
  const selectedCase = search.get('case') || '';
  const runId = search.get('run') || index.runs[0]?.id || '';
  const comparedCase = search.get('result') || '';
  const initialCaseIds = search.get('only') || '';
  const selectedDataset = index.datasets.find(({ id }) => id === datasetId);
  const selectedRun = index.runs.find(({ id }) => id === runId);
  const canLoad = !index.denied && !index.loading;
  const datasetResource = useResource<DatasetDetail>(canLoad && datasetId && ['datasets', 'execute'].includes(view) ? datasetPath(datasetId) : null, revision, active(selectedDataset?.status));
  const caseResource = useResource<CaseDetail>(canLoad && datasetId && selectedCase && view === 'datasets' ? casePath(datasetId, selectedCase) : null, revision, false);
  const runResource = useResource<RunDetail>(canLoad && runId && runViews.includes(view) ? runPath(runId) : null, revision, active(selectedRun?.status));
  const resultResource = useResource<ResultDetail>(canLoad && runId && comparedCase && view === 'compare' ? resultPath(runId, comparedCase) : null, revision, active(selectedRun?.status));
  const progressRun = runResource.value;

  function refresh() {
    setRevision((value) => value + 1);
  }

  function update(values: Record<string, string>) {
    const next = new URLSearchParams(search.toString());
    for (const [key, value] of Object.entries(values)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    const query = next.toString();
    router.replace(`/benchmark${query ? '?' + query : ''}`, { scroll: false });
  }

  function viewRun(id: string) {
    const selected = index.runs.find((run) => run.id === id);
    update({ view: 'execute', run: id, result: '', ...(selected ? { dataset: selected.dataset_id } : {}) });
  }

  function openComparison(caseId: string) {
    update({ view: 'compare', result: caseId });
  }

  function onRun(run: BenchmarkRun) {
    update({ view: 'execute', run: run.id, dataset: run.dataset_id, result: '', only: '' });
    refresh();
  }

  const errors = [...new Set([index.error, datasetResource.error, caseResource.error, runResource.error, resultResource.error].filter(Boolean))];
  const indexEmpty = index.error && !index.datasets.length && !index.runs.length;

  return <div className="bench-page">
    <div className="bench-shell">
      <header className="bench-titlebar">
        <div className="bench-title-group">
          <span className="bench-brand-icon"><ChartNoAxesColumn size={26} strokeWidth={2.15} aria-hidden="true" /></span>
          <div><Link className="bench-back" href="/admin">Administration</Link><h1>PDF2DOCX-BENCH</h1></div>
        </div>
        {!index.denied && <div className="bench-actions bench-header-actions">
          <Button variant="outline" onClick={refresh} aria-label="Refresh benchmark dashboard"><RefreshCw size={17} aria-hidden="true" /><span>Refresh</span></Button>
          <Button onClick={() => update({ view: 'execute', only: '' })}><Play size={16} aria-hidden="true" /> New run</Button>
        </div>}
      </header>
      {index.loading ? <Loading /> : index.denied ? <section className="bench-locked">
        <div className="bench-empty-icon"><LockKeyhole size={23} aria-hidden="true" /></div>
        <h2>Administrator access required</h2>
        <p>Sign in with an administrator account to manage benchmark datasets and view reports.</p>
        <Link href="/login" className={buttonClass()}>Sign in</Link>
      </section> : <div className="bench-workspace">
        <nav className="bench-nav" aria-label="Benchmark navigation">
          {views.map(([key, title, Icon]) => <button
            aria-current={view === key ? 'page' : undefined}
            onClick={() => update({ view: key, ...(key === 'execute' ? { only: '' } : {}) })}
            key={key}><Icon size={17} aria-hidden="true" />{title}</button>)}
        </nav>
        <div className="bench-content">
          {errors.map((message) => <ErrorNotice key={message}>{message}</ErrorNotice>)}
          {indexEmpty ? <Empty title="Benchmark data could not be loaded" action={<Button variant="outline" onClick={refresh}>Try again</Button>} /> : <>
            {runViews.includes(view) && !!index.runs.length && <div className="bench-run-selector">
              <label htmlFor="bench-selected-run">Selected run</label>
              <select id="bench-selected-run" className="field-input" value={runId} onChange={(event) => update({ run: event.target.value, result: '' })}>
                {runId && !index.runs.some((item) => item.id === runId) && <option value={runId}>Loading selected run</option>}
                {index.runs.map((item) => <option key={item.id} value={item.id}>{item.name} · {label(item.status)}</option>)}
              </select>
            </div>}
            {runResource.loading && <Loading label="Loading run" />}
            {view === 'overview' && <Overview run={selectedRun} runs={index.runs}
              openRun={viewRun} openExecution={() => update({ view: 'execute' })} openDatasets={() => update({ view: 'datasets' })} openHistory={() => update({ view: 'history' })} />}
            {view === 'datasets' && <DatasetsView datasets={index.datasets} selectedId={datasetId}
              dataset={datasetResource.value} loading={datasetResource.loading} detail={caseResource.value} detailLoading={caseResource.loading} selectedCase={selectedCase}
              selectDataset={(id) => update({ dataset: id, case: '' })} selectCase={(id) => update({ case: id })}
              onCreated={(dataset) => { update({ dataset: dataset.id, case: '' }); refresh(); }}
              refresh={refresh} onRun={(caseId) => update({ view: 'execute', only: caseId })} />}
            {view === 'execute' && index.config && <>
              <RunForm datasets={index.datasets} datasetId={datasetId} cases={datasetResource.value?.cases ?? []}
                initialCaseIds={initialCaseIds} config={index.config} onDataset={(id) => update({ dataset: id, only: '' })} onRun={onRun} />
              {progressRun && <RunProgress key={progressRun.id} run={progressRun} onRun={onRun} onCompare={openComparison} />}
            </>}
            {view === 'history' && <History runs={index.runs} onSelect={viewRun} />}
            {view === 'compare' && <Comparison run={progressRun} result={resultResource.value} selected={comparedCase} loading={resultResource.loading} onSelect={openComparison} />}
            {view === 'ocr' && <OCRAnalysis run={progressRun} onSelect={openComparison} />}
            {view === 'performance' && <Performance run={progressRun} runs={index.runs} onSelect={openComparison} />}
            {view === 'security' && <Security run={progressRun} />}
            {view === 'failures' && <Failures run={progressRun} onSelect={openComparison} />}
            {view === 'reports' && <Reports run={progressRun} />}
          </>}
        </div>
      </div>}
    </div>
  </div>;
}
