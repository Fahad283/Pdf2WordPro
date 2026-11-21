'use client';

import { useState } from 'react';
import { Download } from 'lucide-react';
import { label, metric, object, percent, points, safeAssetUrl, seconds, type BenchmarkRun, type CaseResult, type MetricsRecord, type PageDiagnostic, type ResultDetail, type RunDetail } from '@/lib/benchmarks';
import { fileSize } from '@/lib/utils';
import { buttonClass } from '@/components/ui/button';
import { Bar, Empty, Facts, Loading, NoticeList, Panel, Status, scalar } from './common';
import { ResultTable } from './runs';

type CaseSelect = (id: string) => void;

const qualityFields: [string, string, (value: unknown) => string][] = [
  ['text_accuracy', 'Text accuracy', percent],
  ['cer', 'Character error rate', percent],
  ['wer', 'Word error rate', percent],
  ['layout_similarity', 'Layout similarity', percent],
  ['tables_score', 'Table preservation', percent],
  ['images_score', 'Image preservation', percent],
  ['page_completeness', 'Page completeness', percent],
  ['ocr_accuracy', 'OCR accuracy', percent],
  ['docx_valid', 'DOCX validity', scalar],
  ['duration_seconds', 'Conversion time', seconds],
  ['size_bytes', 'DOCX size', byteSize],
];

function byteSize(value: unknown) {
  const bytes = metric(value);
  return bytes === undefined ? '—' : fileSize(bytes);
}

function metricPairs(actual: MetricsRecord) {
  return Object.entries(actual)
    .filter(([, value]) => value !== null && ['number', 'boolean', 'string'].includes(typeof value))
    .map(([key, value]): [string, string] => [label(key), scalar(value)]);
}

function renderableAssets(input?: Record<string, string>) {
  return Object.fromEntries(Object.entries(input ?? {})
    .filter(([, address]) => typeof address === 'string' && safeAssetUrl(address)));
}

export function Comparison({ run, result, selected, loading, onSelect }: {
  run?: RunDetail;
  result?: ResultDetail;
  selected: string;
  loading: boolean;
  onSelect: CaseSelect;
}) {
  const [showCompleted, setShowCompleted] = useState(false);
  const rows = (run?.results ?? []).filter((entry) => !showCompleted || entry.status === 'completed');

  return <div className="bench-stack">
    <Panel title="Document comparison" description="Open a test case to inspect its output and page diagnostics.">
      {run?.results.length ? <>
        <div className="bench-filters">
          <label>Test case<select className="field-input" value={selected} onChange={(event) => onSelect(event.target.value)}>
            <option value="">Select a test case</option>{rows.map((entry) => <option key={entry.case_id} value={entry.case_id}>{entry.case_id} · {label(entry.category)} · {label(entry.status)}</option>)}
          </select></label>
          <label className="bench-checkbox"><input type="checkbox" checked={showCompleted} onChange={(event) => setShowCompleted(event.target.checked)} /> Completed cases only</label>
        </div>
      </> : <Empty title="No case results to compare" />}
    </Panel>
    {loading && <Loading label="Loading case diagnostics" />}
    {result && <CaseComparison key={result.case_id} result={result} />}
  </div>;
}

function CaseComparison({ result }: { result: ResultDetail }) {
  const details = result.details;
  const reference = details?.reference;
  const assets = renderableAssets({ ...result.assets, ...result.artifact_urls, ...details?.artifacts });
  const referenceAssets = renderableAssets(reference?.artifacts);
  const actual: MetricsRecord = { ...result.metrics, ...details?.metrics, duration_seconds: result.duration_seconds };
  const referenceMeasures: MetricsRecord = { ...reference?.metrics, duration_seconds: reference?.duration_seconds };
  const hasReference = Boolean(reference && (Object.keys(reference?.metrics ?? {}).length || Object.keys(referenceAssets).length));
  const resources = [
    ['Original PDF', assets.source_pdf],
    ['Converted DOCX', assets.produced_docx],
    ['Rendered PDF', assets.rendered_pdf],
    ['Reference DOCX', referenceAssets.produced_docx || referenceAssets.reference_docx || assets.reference_docx],
    ['Rendered reference PDF', referenceAssets.rendered_pdf || assets.reference_rendered_pdf],
  ];
  const measured = qualityFields.filter(([key]) => actual[key] !== undefined || referenceMeasures[key] !== undefined);
  return <>
    <Panel title={result.case_id} description={label(result.category)} action={<Status value={result.status} passed={result.passed} />}>
      <Facts entries={[
        ['Case score', points(result.score)], ['Conversion duration', seconds(result.duration_seconds)], ['Outcome', result.error || label(result.status)],
      ]} />
      <NoticeList title="Critical findings" items={details?.critical} critical />
      <NoticeList title="Conversion notes" items={details?.warnings} />
      <NoticeList title="Reference findings" items={reference?.critical} critical />
      <NoticeList title="Reference notes" items={reference?.warnings} />
      {reference?.notes && <p className="bench-muted">{reference.notes}</p>}
      <div className="bench-actions">{resources.filter((entry) => entry[1]).map(([name, url]) =>
        <a className={buttonClass('outline')} href={url} key={name} download><Download size={16} aria-hidden="true" />{name}</a>,
      )}</div>
    </Panel>
    {!!measured.length && <Panel title="Quality measurements" description={hasReference ? `Reference provider · ${reference?.provider || 'Manual upload'}` : undefined}>
      <div className="bench-table-scroll"><table className="bench-table">
        <thead><tr><th scope="col">Metric</th><th scope="col">Converter output</th>{hasReference && <th scope="col">{reference?.provider || 'Reference'}</th>}</tr></thead>
        <tbody>{measured.map(([key, title, format]) => <tr key={key}><th scope="row">{title}</th><td>{format(actual[key])}</td>{hasReference && <td>{format(referenceMeasures[key])}</td>}</tr>)}</tbody>
      </table></div>
      {!!metricPairs(actual).length && <details className="bench-action-details"><summary>All measured fields</summary><Facts entries={metricPairs(actual)} /></details>}
    </Panel>}
    <VisualPages key={result.case_id} pages={details?.pages ?? []} referencePages={reference?.pages ?? []} assets={assets} referenceAssets={referenceAssets} />
    {details?.extracted && <TextComparison text={details.extracted} reference={reference?.extracted} />}
    <TableDetails metrics={actual} reference={referenceMeasures} extracted={details?.extracted} />
  </>;
}

function pageNumber(page: PageDiagnostic) {
  return metric(page.source_page) ?? metric(page.page) ?? metric(page.page_number);
}

function padded(page: number) {
  return page.toString().padStart(3, '0');
}

function assetNumbers(assets: Record<string, string>) {
  return Object.keys(assets).flatMap((key) => {
    const match = /^original_(\d+)$/.exec(key);
    return match ? [Number(match[1])] : [];
  });
}

function pageAsset(assets: Record<string, string>, page: PageDiagnostic | undefined, role: string, number: number) {
  return safeAssetUrl(page?.artifacts?.[role]) || assets[`${role}_${padded(number)}`];
}

function VisualPages({ pages, referencePages, assets, referenceAssets }: {
  pages: PageDiagnostic[];
  referencePages: PageDiagnostic[];
  assets: Record<string, string>;
  referenceAssets: Record<string, string>;
}) {
  const pageChoices = [...new Set([...pages, ...referencePages].flatMap((item) => pageNumber(item) ?? [])
    .concat(assetNumbers(assets), assetNumbers(referenceAssets)))].sort((left, right) => left - right);
  const [selected, setSelected] = useState<number>();
  const [display, setDisplay] = useState<'side-by-side' | 'difference' | 'overlay'>('side-by-side');
  const [opacity, setOpacity] = useState(55);
  if (!pageChoices.length) return <Panel title="Visual diagnostics"><Empty title="No visual artifacts available">The selected case may have been rejected or rendering did not produce comparison pages.</Empty></Panel>;
  const number = selected && pageChoices.includes(selected) ? selected : pageChoices[0];
  const page = pages.find((item) => pageNumber(item) === number);
  const referencePage = referencePages.find((item) => pageNumber(item) === number);
  const original = pageAsset(assets, page, 'original', number) || pageAsset(referenceAssets, referencePage, 'original', number);
  const rendered = pageAsset(assets, page, 'rendered', number);
  const difference = pageAsset(assets, page, 'difference', number);
  const reference = pageAsset(referenceAssets, referencePage, 'rendered', number);
  const referenceDiff = pageAsset(referenceAssets, referencePage, 'difference', number);
  const pageFacts = page ? [
    ['Source page', scalar(number)],
    ['Matched output page', scalar(page.rendered_page ?? page.output_page)],
    ['SSIM', percent(page.ssim)],
    ['Layout similarity', percent(page.layout_similarity ?? page.similarity)],
    ['Text block position', percent(page.text_block_score ?? page.text_position_score)],
    ['Image position', percent(page.image_position_score ?? page.image_score)],
  ] satisfies [string, string][] : [];
  return <Panel title="Visual diagnostics" description="Matched pages and rendered differences from the selected test case.">
    <div className="bench-filters">
      <label>Source page<select className="field-input" value={number} onChange={(event) => setSelected(Number(event.target.value))}>
        {pageChoices.map((candidate) => <option value={candidate} key={candidate}>Page {candidate}</option>)}
      </select></label>
      <label>Display<select className="field-input" value={display} onChange={(event) => setDisplay(event.target.value as typeof display)}>
        <option value="side-by-side">Side by side</option><option value="difference">Difference maps</option><option value="overlay">Overlay</option>
      </select></label>
    </div>
    {display === 'overlay' ? <div className="bench-stack">
      {original && rendered ? <>
        <label className="bench-slider">Converted page opacity <output>{opacity}%</output>
          <input type="range" min={0} max={100} value={opacity} onChange={(event) => setOpacity(Number(event.target.value))} />
        </label>
        <div className="bench-overlay">
          {/* These images require the authenticated browser session. */}
          {/* eslint-disable @next/next/no-img-element */}
          <img src={original} alt={`Original page ${number}`} />
          <img src={rendered} className="bench-overlay-top" style={{ opacity: opacity / 100 }} alt={`Converted page ${number} overlay`} />
        </div>
      </> : <Empty title="This page has no matched image pair" />}
    </div> : display === 'difference' ? <div className="bench-image-grid">
      <PageImage name="Conversion difference" url={difference} page={number} />
      {referenceDiff && <PageImage name="Reference difference" url={referenceDiff} page={number} />}
    </div> : <div className={`bench-image-grid ${reference ? 'bench-image-grid-three' : ''}`}>
      <PageImage name="Original PDF" url={original} page={number} />
      <PageImage name="Converted output" url={rendered} page={number} />
      {reference && <PageImage name="Reference output" url={reference} page={number} />}
    </div>}
    <Facts entries={pageFacts} />
    <NoticeList title="Page findings" items={page?.warnings} />
    <NoticeList title="Reference page findings" items={referencePage?.warnings} />
    {page && <details className="bench-action-details"><summary>Page geometry and diagnostics</summary>
      <pre className="bench-code">{JSON.stringify(Object.fromEntries(Object.entries(page).filter(([key]) => key !== 'artifacts')), null, 2)}</pre>
    </details>}
  </Panel>;
}

function PageImage({ name, url, page }: { name: string; url?: string; page: number }) {
  const [broken, setBroken] = useState(false);
  return <figure className="bench-page-image" key={url}>
    <figcaption>{name}</figcaption>
    {url && !broken ? <a href={url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${name.toLowerCase()} page ${page} at full size`}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={url} loading="lazy" onError={() => setBroken(true)} alt={`${name} page ${page}`} />
    </a> : <div className="bench-image-empty">{broken ? 'Preview could not be loaded' : 'No matched page'}</div>}
  </figure>;
}

function TextComparison({ text, reference }: { text: Record<string, string>; reference?: Record<string, string> }) {
  const [normalized, setNormalized] = useState(false);
  const expected = normalized ? text.normalized_expected : text.raw_expected;
  const actual = normalized ? text.normalized_actual : text.raw_actual;
  const comparator = normalized ? reference?.normalized_actual : reference?.raw_actual;
  return <Panel title="Extracted text" action={<label className="bench-checkbox"><input type="checkbox" checked={normalized} onChange={(event) => setNormalized(event.target.checked)} /> Normalize text</label>}>
    <div className="bench-text-grid">
      {[
        ['Expected text', expected],
        ['Converted text', actual],
        ...(comparator !== undefined ? [['Reference text', comparator]] : []),
      ].map(([title, content]) => <div key={title}><h3>{title}</h3><pre className="bench-code bench-text-preview" dir="auto">{content ?? 'Text was unavailable.'}</pre></div>)}
    </div>
  </Panel>;
}

function TableDetails({ metrics, reference, extracted }: { metrics: MetricsRecord; reference: MetricsRecord; extracted?: Record<string, string> }) {
  const tableFacts = Object.entries(metrics).filter(([key]) => /table/.test(key));
  const referenceFacts = Object.entries(reference).filter(([key]) => /table/.test(key));
  const extractionFacts = Object.entries(extracted ?? {}).filter(([key]) => /table/.test(key));
  if (!tableFacts.length && !referenceFacts.length && !extractionFacts.length) return null;
  return <Panel title="Table diagnostics">
    <Facts entries={tableFacts.filter(([, value]) => typeof value !== 'object' && value !== null).map(([key, value]) => [label(key), scalar(value)])} />
    {tableFacts.filter(([, value]) => value != null && typeof value === 'object').map(([key, value]) => <details className="bench-action-details" key={key}><summary>{label(key)}</summary><pre className="bench-code">{JSON.stringify(value, null, 2)}</pre></details>)}
    {extractionFacts.map(([key, value]) => <details className="bench-action-details" key={key}><summary>{label(key)}</summary><pre className="bench-code">{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</pre></details>)}
    {!!referenceFacts.length && <details className="bench-action-details"><summary>Reference table measurements</summary><Facts entries={referenceFacts.map(([key, value]) => [label(key), scalar(value)])} /></details>}
  </Panel>;
}

function diagnostics(run?: RunDetail) {
  return run?.results ?? [];
}

export function OCRAnalysis({ run, onSelect }: { run?: RunDetail; onSelect: CaseSelect }) {
  const data = object(run?.summary?.metrics);
  const cases = diagnostics(run).filter((entry) => {
    return metric(entry.metrics.ocr_accuracy) !== undefined || Boolean(entry.metrics.ocr_used) || /ocr|scan|rtl|multilingual/i.test(entry.category);
  });
  return <Panel title="OCR and language analysis" description="Inspect recognized text, error rates, and right-to-left document structure.">
    <Facts entries={[
      ['OCR accuracy', percent(data.ocr_accuracy)], ['OCR character error rate', percent(data.ocr_cer)],
      ['OCR word error rate', percent(data.ocr_wer)], ['Language support', percent(data.language_score)],
    ]} />
    {!cases.length ? <Empty title="No OCR cases in this run" /> : <div className="bench-table-scroll"><table className="bench-table">
      <thead><tr><th scope="col">Case</th><th scope="col">Character error</th><th scope="col">Word error</th><th scope="col">Confidence</th><th scope="col">Language score</th><th scope="col">RTL text</th><th scope="col">Status</th></tr></thead>
      <tbody>{cases.map((entry) => <tr key={entry.case_id}>
        <th scope="row"><button className="bench-text-button" onClick={() => onSelect(entry.case_id)}>{entry.case_id}</button></th>
        <td>{percent(entry.metrics.cer)}</td><td>{percent(entry.metrics.wer)}</td>
        <td>{scalar(entry.metrics.ocr_confidence)}</td><td>{percent(entry.metrics.language_score)}</td>
        <td>{scalar(entry.metrics.rtl_paragraphs ?? entry.metrics.rtl)}</td><td><Status value={entry.status} passed={entry.passed} /></td>
      </tr>)}</tbody>
    </table></div>}
  </Panel>;
}

export function Performance({ run, runs, onSelect }: { run?: RunDetail; runs: BenchmarkRun[]; onSelect: CaseSelect }) {
  const summary = object(run?.summary);
  const measured = diagnostics(run).filter((entry) => metric(entry.duration_seconds) !== undefined);
  const durationHistory = runs
    .filter((item) => item.dataset_id === run?.dataset_id && metric(item.summary?.median_seconds) !== undefined)
    .slice(0, 12).reverse();
  const max = Math.max(0, ...durationHistory.map((item) => Number(item.summary?.median_seconds)));
  return <div className="bench-stack">
    <Panel title="Conversion performance" description="Latencies and worker resource measurements from the selected run.">
      <Facts entries={[
        ['Cases measured', measured.length],
        ['Mean', seconds(summary.mean_duration_seconds)], ['Median', seconds(summary.median_seconds)],
        ['p95', seconds(summary.p95_seconds)], ['p99', seconds(summary.p99_seconds)],
        ['Run wall time', seconds(summary.wall_seconds ?? summary.duration_seconds)],
      ]} />
      {!measured.length ? <Empty title="No timing samples yet" /> : <div className="bench-table-scroll bench-result-table"><table className="bench-table">
        <thead><tr><th scope="col">Case</th><th scope="col">Conversion</th><th scope="col">Parsing</th><th scope="col">OCR</th><th scope="col">DOCX generation</th><th scope="col">CPU time</th><th scope="col">Peak memory</th><th scope="col">Temporary files</th></tr></thead>
        <tbody>{measured.map((entry) => {
          const fields = { ...entry.metrics, ...object(entry.metrics.performance) };
          return <tr key={entry.case_id}>
            <th scope="row"><button className="bench-text-button" onClick={() => onSelect(entry.case_id)}>{entry.case_id}</button></th>
            <td>{seconds(entry.duration_seconds)}</td><td>{seconds(fields.parse_seconds ?? fields.pdf_parse_seconds)}</td>
            <td>{seconds(fields.ocr_seconds)}</td><td>{seconds(fields.docx_seconds ?? fields.docx_generation_seconds)}</td>
            <td>{seconds(fields.cpu_seconds)}</td><td>{byteSize(fields.peak_rss_bytes ?? fields.peak_memory_bytes)}</td>
            <td>{byteSize(fields.temp_bytes ?? fields.temporary_bytes)}</td>
          </tr>;
        })}</tbody>
      </table></div>}
    </Panel>
    <Panel title="Median conversion time by run" description="Completed runs for the same dataset revision.">
      {!durationHistory.length ? <Empty title="No historical timing samples" /> : <div className="bench-category-grid">
        {durationHistory.map((entry) => <div className="bench-category" key={entry.id}><div><span>{entry.name}</span><strong>{seconds(entry.summary?.median_seconds)}</strong></div>
          <Bar value={Number(entry.summary?.median_seconds)} max={max} />
        </div>)}
      </div>}
    </Panel>
  </div>;
}

export function Security({ run }: { run?: RunDetail }) {
  const raw = run?.summary?.security;
  const checks = Array.isArray(raw) ? raw.map(object) : [];
  return <Panel title="Security and reliability checks" description="Recorded checks for the selected benchmark run.">
    {!checks.length ? <Empty title="No security checks recorded" /> : <div className="bench-table-scroll"><table className="bench-table">
      <thead><tr><th scope="col">Check</th><th scope="col">Status</th><th scope="col">Evidence</th></tr></thead>
      <tbody>{checks.map((row, index) => <tr key={String(row.id ?? index)}>
        <th scope="row">{scalar(row.name ?? row.id)}</th>
        <td><Status value={row.passed == null ? 'unmeasured' : 'completed'} passed={typeof row.passed === 'boolean' ? row.passed : undefined} /></td>
        <td>{scalar(row.detail)}</td>
      </tr>)}</tbody>
    </table></div>}
  </Panel>;
}

export function Failures({ run, onSelect }: { run?: RunDetail; onSelect: CaseSelect }) {
  const failed = diagnostics(run).filter((entry: CaseResult) => entry.status === 'failed' || entry.passed === false);
  return <Panel title="Failure reports" description="Open a case to inspect the recorded error, warnings, and available page evidence.">
    {run?.error && <NoticeList title="Run error" items={[run.error]} critical />}
    {failed.length ? <ResultTable results={failed} select={onSelect} /> : <Empty title={run?.summary ? 'No failed cases recorded' : 'No completed results to review'} />}
  </Panel>;
}
