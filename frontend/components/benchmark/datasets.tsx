'use client';

import { useMemo, useState, type FormEvent } from 'react';
import { Database, FilePlus2, Download, Search, Upload } from 'lucide-react';
import { errorText, json } from '@/lib/api';
import { active, casePath, datasetPath, fetchBench, formatTime, label, safeAssetUrl, seconds, type CaseDetail, type Dataset, type DatasetCase, type DatasetDetail } from '@/lib/benchmarks';
import { fileSize } from '@/lib/utils';
import { Button, buttonClass } from '@/components/ui/button';
import { Empty, ErrorNotice, Facts, Loading, Panel, Status } from './common';

type Change = () => void;

function CreateDataset({ onCreated }: { onCreated: (dataset: Dataset) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = new FormData(form);
    setBusy(true);
    setError('');
    try {
      const dataset = await fetchBench<Dataset>('/datasets', json('POST', {
        name: String(input.get('name')).trim(),
        version: String(input.get('version')).trim(),
      }));
      form.reset();
      onCreated(dataset);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  return <details className="bench-action-details">
    <summary><FilePlus2 size={17} aria-hidden="true" /> Create a dataset revision</summary>
    <form className="bench-form" onSubmit={(event) => void create(event)}>
      <div className="bench-form-grid">
        <label>Dataset name<input className="field-input" name="name" placeholder="Invoice regression suite" maxLength={100} required /></label>
        <label>Version<input className="field-input" name="version" placeholder="1.0.0" maxLength={40} required /></label>
      </div>
      <ErrorNotice>{error}</ErrorNotice>
      <Button type="submit" disabled={busy}>{busy ? 'Creating…' : 'Create dataset'}</Button>
    </form>
  </details>;
}

function validateObject(value: FormDataEntryValue | null, labelText: string) {
  try {
    const parsed = JSON.parse(String(value ?? ''));
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new Error();
    return parsed as Record<string, unknown>;
  } catch {
    throw new Error(`${labelText} must be a JSON object.`);
  }
}

function AddCase({ datasetId, onChanged }: { datasetId: string; onChanged: Change }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = new FormData(form);
    setError('');
    setSaved(false);
    setBusy(true);
    try {
      const truth = validateObject(input.get('ground_truth'), 'Ground truth');
      if (!Array.isArray(truth.pages) || !truth.pages.length) {
        throw new Error('Provide ground truth with a pages array containing at least one expected page.');
      }
      input.set('ground_truth', JSON.stringify(truth));
      if (String(input.get('settings')).trim()) {
        input.set('settings', JSON.stringify(validateObject(input.get('settings'), 'Conversion settings')));
      } else {
        input.delete('settings');
      }
      await fetchBench(`${datasetPath(datasetId)}/cases`, { method: 'POST', body: input });
      form.reset();
      setSaved(true);
      onChanged();
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  return <details className="bench-action-details">
    <summary><Upload size={17} aria-hidden="true" /> Add a test PDF</summary>
    <form className="bench-form" onSubmit={(event) => void upload(event)}>
      <div className="bench-form-grid">
        <label>PDF file<input className="bench-file" type="file" name="file" accept=".pdf,application/pdf" required /></label>
        <label>Case ID<input className="field-input" name="case_id" placeholder="PDF-101" pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,47}" maxLength={48} required /></label>
        <label>Category<input className="field-input" name="category" placeholder="digital" pattern="[a-z0-9][a-z0-9-]{0,59}" maxLength={60} required /></label>
      </div>
      <label>Description<input className="field-input" name="description" maxLength={240} required /></label>
      <label>Ground truth (JSON)<textarea name="ground_truth" className="field-input bench-editor" rows={5}
        placeholder={'{"pages":[{"text":"Expected page text","width":612,"height":792}],"languages":["eng"],"ocr_required":false}'}
        required />
        <small>Provide text in reading order and dimensions in PDF points for every page of an unencrypted PDF. Tables, images, and features can be included.</small>
      </label>
      <label>Conversion settings (optional JSON)<textarea name="settings" className="field-input bench-editor" rows={2} placeholder={'{"ocr":"force","languages":["eng"]}'} /></label>
      <ErrorNotice>{error}</ErrorNotice>{saved && <p role="status" className="success-text">Test case added.</p>}
      <Button type="submit" disabled={busy}>{busy ? 'Uploading…' : 'Upload test case'}</Button>
    </form>
  </details>;
}

function ReferenceForm({ datasetId, detail, onChanged }: { datasetId: string; detail: CaseDetail; onChanged: Change }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = new FormData(form);
    input.set('source_sha256', detail.sha256);
    if (!String(input.get('duration_seconds')).trim()) input.delete('duration_seconds');
    setBusy(true);
    setError('');
    setSaved(false);
    try {
      await fetchBench(`${casePath(datasetId, detail.case_id)}/reference`, { method: 'POST', body: input });
      form.reset();
      setSaved(true);
      onChanged();
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  const reference = detail.reference;
  return <div className="bench-stack">
    {reference ? <Facts entries={[
      ['Provider', reference.provider || 'Manual reference'],
      ['Recorded duration', seconds(reference.duration_seconds)],
      ['Source SHA-256', <code className="bench-hash">{reference.source_sha256 ?? detail.sha256}</code>],
      ...(reference.notes ? [['Conditions', reference.notes] as [string, string]] : []),
    ]} /> : <p className="bench-muted">No reference output recorded for this case.</p>}
    <details className="bench-action-details">
      <summary><Upload size={17} aria-hidden="true" /> {reference ? 'Upload another reference' : 'Upload a reference DOCX'}</summary>
      <form className="bench-form" onSubmit={(event) => void upload(event)}>
        <p className="bench-muted">Convert the original PDF with the reference provider and record the settings used. The upload is linked to this source file’s SHA-256.</p>
        <div className="bench-form-grid">
          <label>Reference DOCX<input className="bench-file" name="file" type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document" required /></label>
          <label>Provider<input className="field-input" name="provider" defaultValue="iLovePDF" maxLength={100} required /></label>
          <label>Recorded duration (seconds)<input className="field-input" name="duration_seconds" type="number" min={.001} max={86400} step="any" inputMode="decimal" /></label>
        </div>
        <label>Settings or conditions<textarea className="field-input" name="notes" rows={2} maxLength={1000} /></label>
        <ErrorNotice>{error}</ErrorNotice>{saved && <p role="status" className="success-text">Reference recorded. It will be evaluated in subsequent runs.</p>}
        <Button type="submit" disabled={busy}>{busy ? 'Uploading…' : 'Save reference'}</Button>
      </form>
    </details>
  </div>;
}

function CaseDetails({ datasetId, detail, onChanged, onRun }: {
  datasetId: string;
  detail: CaseDetail;
  onChanged: Change;
  onRun: (caseId: string) => void;
}) {
  const [pageIndex, setPageIndex] = useState(0);
  const pages = detail.ground_truth?.pages ?? [];
  const page = pages[pageIndex];
  const reference = detail.reference;
  const sourceUrl = safeAssetUrl(detail.source_url || detail.assets?.source_pdf);
  const referenceUrl = safeAssetUrl(detail.reference_url || reference?.download_url);
  return <Panel title={detail.case_id} description={detail.description} className="bench-case-detail"
    action={<Button variant="outline" onClick={() => onRun(detail.case_id)}>Run this case</Button>}>
    <Facts entries={[
      ['Category', label(detail.category)],
      ['Expected behavior', detail.behavior === 'reject' ? 'Reject invalid input' : 'Convert'],
      ['PDF size', fileSize(detail.size_bytes)],
      ['Source SHA-256', <code className="bench-hash">{detail.sha256}</code>],
      ...(detail.expected_error ? [['Expected error', detail.expected_error] as [string, string]] : []),
    ]} />
    <div className="bench-actions">
      {sourceUrl && <a href={sourceUrl} className={buttonClass('outline')} download><Download size={16} aria-hidden="true" /> Original PDF</a>}
      {referenceUrl && <a href={referenceUrl} className={buttonClass('outline')} download><Download size={16} aria-hidden="true" /> Reference DOCX</a>}
    </div>
    <details className="bench-action-details" open>
      <summary>Ground truth</summary>
      <div className="bench-details-inner">
        <Facts entries={[
          ['Expected pages', pages.length],
          ['Languages', detail.ground_truth?.languages?.join(', ') || '—'],
          ['OCR required', detail.ground_truth?.ocr_required ? 'Yes' : 'No'],
          ...Object.entries(detail.ground_truth?.features ?? {}).map(([key, value]): [string, number] => [label(key), value]),
        ]} />
        {page && <>
          <label className="bench-inline-field">Expected page
            <select className="field-input" value={pageIndex} onChange={(event) => setPageIndex(Number(event.target.value))}>
              {pages.map((_, index) => <option key={index} value={index}>Page {index + 1}</option>)}
            </select>
          </label>
          <p className="bench-muted">{[page.width && page.height ? `${page.width} × ${page.height} pt` : null, `${page.tables?.length ?? 0} tables`, `${page.images?.length ?? 0} images`].filter(Boolean).join(' · ')}</p>
          <pre className="bench-code" dir="auto">{page.text || 'No text expected on this page.'}</pre>
        </>}
      </div>
    </details>
    {detail.behavior === 'convert' && <details className="bench-action-details" open>
      <summary>Commercial reference</summary>
      <div className="bench-details-inner"><ReferenceForm datasetId={datasetId} detail={detail} onChanged={onChanged} /></div>
    </details>}
  </Panel>;
}

export function DatasetsView({ datasets, selectedId, dataset, loading, detail, detailLoading, selectedCase, selectDataset, selectCase, onCreated, refresh, onRun }: {
  datasets: Dataset[];
  selectedId: string;
  dataset?: DatasetDetail;
  loading: boolean;
  detail?: CaseDetail;
  detailLoading: boolean;
  selectedCase: string;
  selectDataset: (id: string) => void;
  selectCase: (id: string) => void;
  onCreated: (dataset: Dataset) => void;
  refresh: Change;
  onRun: (caseId: string) => void;
}) {
  const [category, setCategory] = useState('');
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const categories = useMemo(() => Array.from(new Set(dataset?.cases.map((entry) => entry.category))).sort(), [dataset]);
  const filtered = (dataset?.cases ?? []).filter((entry) =>
    (!category || entry.category === category) && `${entry.case_id} ${entry.description} ${entry.category}`.toLowerCase().includes(search.trim().toLowerCase()),
  );

  async function seed() {
    setBusy(true);
    setError('');
    try {
      onCreated(await fetchBench<Dataset>('/datasets/synthetic', json('POST')));
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  return <div className="bench-stack">
    <Panel title="Dataset manager" description="Versioned test PDFs, expected content, and reference outputs."
      action={<Button variant="outline" onClick={() => void seed()} disabled={busy || datasets.some((item) => item.name === 'Synthetic PDF corpus' && active(item.status))}>
        <Database size={16} aria-hidden="true" />{busy ? 'Requesting…' : 'Generate synthetic corpus'}
      </Button>}>
      <ErrorNotice>{error}</ErrorNotice>
      {datasets.length ? <label className="bench-field">Dataset revision
        <select className="field-input" value={selectedId} onChange={(event) => { setCategory(''); setSearch(''); selectDataset(event.target.value); }}>
          {datasets.map((item) => <option key={item.id} value={item.id}>{item.name} · v{item.version}</option>)}
        </select>
      </label> : <Empty title="No benchmark datasets">Generate the original test corpus or create a revision for your own fixtures.</Empty>}
      <CreateDataset onCreated={onCreated} />
    </Panel>
    {loading && <Loading label="Loading dataset revision" />}
    {dataset && <Panel title={dataset.name} description={`Version ${dataset.version} · ${dataset.case_count} cases · Created ${formatTime(dataset.created_at)}`}
      action={<Status value={dataset.status} />}>
      <ErrorNotice>{dataset.error}</ErrorNotice>
      {active(dataset.status) && <p className="bench-muted" role="status">The dataset is being prepared. Cases appear when generation finishes.</p>}
      {dataset.manifest_sha256 && <Facts entries={[['Manifest SHA-256', <code className="bench-hash">{dataset.manifest_sha256}</code>]]} />}
      {!!dataset.cases.length && <>
        <div className="bench-filters">
          <label className="bench-search"><Search size={17} aria-hidden="true" /><input className="field-input" type="search" aria-label="Find test cases" placeholder="Search test cases" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
          <label className="bench-select-filter"><span className="sr-only">Category</span><select className="field-input" value={category} onChange={(event) => setCategory(event.target.value)}>
            <option value="">All categories</option>{categories.map((value) => <option key={value} value={value}>{label(value)}</option>)}
          </select></label>
        </div>
        <CaseTable cases={filtered} selectedCase={selectedCase} selectCase={selectCase} />
      </>}
      {dataset.status === 'ready' && !dataset.locked && <AddCase key={dataset.id} datasetId={dataset.id} onChanged={refresh} />}
    </Panel>}
    {detailLoading && <Loading label="Loading test case" />}
    {dataset && detail && <CaseDetails key={detail.case_id} datasetId={dataset.id} detail={detail} onChanged={refresh} onRun={onRun} />}
  </div>;
}

function CaseTable({ cases, selectedCase, selectCase }: { cases: DatasetCase[]; selectedCase: string; selectCase: (id: string) => void }) {
  if (!cases.length) return <Empty title="No matching cases">Try a different search or category.</Empty>;
  return <div className="bench-table-scroll bench-case-table"><table className="bench-table">
    <thead><tr><th scope="col">Case</th><th scope="col">Description</th><th scope="col">Category</th><th scope="col">Expected</th><th scope="col">Reference</th></tr></thead>
    <tbody>{cases.map((entry) => <tr key={entry.case_id} className={selectedCase === entry.case_id ? 'bench-row-selected' : ''}>
      <th scope="row"><button className="bench-text-button" onClick={() => selectCase(entry.case_id)} aria-pressed={selectedCase === entry.case_id}>{entry.case_id}</button></th>
      <td>{entry.description}</td>
      <td>{label(entry.category)}</td>
      <td>{entry.behavior === 'reject' ? 'Reject' : 'Convert'}</td>
      <td>{entry.has_reference ? 'Recorded' : '—'}</td>
    </tr>)}</tbody>
  </table></div>;
}
