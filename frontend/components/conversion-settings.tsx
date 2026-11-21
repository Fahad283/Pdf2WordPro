'use client';

import { useId } from 'react';
import { ChevronDown, Settings2 } from 'lucide-react';
import { z } from 'zod';
import type { Config, FileRecord } from '@/lib/api';
import type { ToolId } from '@/lib/tools';

export const languageNames: Record<string, string> = { eng: 'English', urd: 'Urdu', ara: 'Arabic', deu: 'German', fra: 'French', spa: 'Spanish', ita: 'Italian', por: 'Portuguese', hin: 'Hindi', ben: 'Bengali', jpn: 'Japanese', chi_sim: 'Simplified Chinese', chi_tra: 'Traditional Chinese', rus: 'Russian', osd: 'Script detection' };

const preserve = [
  ['preserve_images', 'Images'], ['preserve_tables', 'Tables'], ['preserve_columns', 'Columns'],
  ['preserve_headers_footers', 'Headers and footers'], ['preserve_hyperlinks', 'Links'],
  ['preserve_page_size', 'Page size'], ['preserve_page_breaks', 'Page breaks'],
] as const;

const pageSchema = z.string().regex(/^\s*\d+\s*(?:-\s*\d+\s*)?(?:,\s*\d+\s*(?:-\s*\d+\s*)?)*$/, 'Enter pages such as 1-3, 5.');

const modes = [
  ['editable', 'Editable layout', 'Rebuild text, tables, and images as Word elements.'],
  ['flowing', 'Flowing text', 'Prioritize reading order in a continuous document.'],
  ['visual', 'Visual layout', 'Keep each page as an image with no editable text.'],
] as const;

export type Options = Record<string, string | number | boolean | string[]>;

export const defaults: Options = {
  mode: 'editable', ocr: 'auto', languages: ['eng'], pages: '', page_selection: 'all', rotation: 90, compression: 'balanced',
  split_mode: 'pages', dpi: 150, start_number: 1, text: '', password: '',
  ...Object.fromEntries(preserve.map(([key]) => [key, true])),
};

const pageTools = new Set<ToolId>(['pdf-to-word', 'split-pdf', 'rotate-pdf', 'extract-pages', 'delete-pages', 'pdf-to-jpg', 'watermark-pdf', 'page-numbers', 'ocr-pdf']);
const requirePages = new Set<ToolId>(['extract-pages', 'delete-pages']);

export function makeSettings(tool: ToolId, options: Options, records: FileRecord[]) {
  const settings: Options = {};
  function take(...names: string[]) { for (const name of names) settings[name] = options[name]; }
  if (pageTools.has(tool)) {
    const raw = String(options.pages).trim();
    if (!raw && (requirePages.has(tool) || options.page_selection !== 'all')) throw new Error('Select the pages to use.');
    if (raw) {
      const parsed = pageSchema.safeParse(raw);
      if (!parsed.success) throw new Error(parsed.error.issues[0].message);
      const max = Math.min(...records.map((record) => record.page_count ?? Infinity));
      for (const part of raw.replace(/\s+/g, '').split(',')) {
        const [first, last = first] = part.split('-').map(Number);
        if (!Number.isSafeInteger(first) || !Number.isSafeInteger(last) || first < 1 || last < first || last > max) {
          throw new Error('The selected pages must exist in every selected PDF.');
        }
      }
      settings.pages = raw.replace(/\s+/g, '');
      if (settings.pages.length > 1500) throw new Error('The page selection is too long. Combine adjacent pages into ranges.');
    }
  }
  if (tool === 'pdf-to-word') {
    take('mode', ...preserve.map(([key]) => key));
    if (options.mode === 'visual') settings.ocr = 'off';
  }
  if (tool === 'ocr-pdf' || (tool === 'pdf-to-word' && options.mode !== 'visual')) {
    take('ocr');
    if (options.ocr !== 'off') {
      if (!(options.languages as string[]).length) throw new Error('Select at least one OCR language.');
      take('languages');
    }
  }
  if (tool === 'split-pdf') take('split_mode');
  if (tool === 'rotate-pdf') take('rotation');
  if (tool === 'compress-pdf') take('compression');
  if (tool === 'pdf-to-jpg') take('dpi');
  if (tool === 'page-numbers') {
    if (!Number.isSafeInteger(options.start_number) || Number(options.start_number) < 1 || Number(options.start_number) > 1000000) throw new Error('Enter a starting page number from 1 to 1,000,000.');
    take('start_number');
  }
  if (tool === 'watermark-pdf') {
    if (!String(options.text).trim()) throw new Error('Enter the text for the watermark.');
    take('text');
  }
  if (tool === 'protect-pdf' || tool === 'unlock-pdf' || records.some((record) => record.encrypted)) {
    const password = String(options.password);
    if (tool === 'protect-pdf' && (password.length < 8 || new TextEncoder().encode(password).length > 32)) {
      throw new Error('Enter a password with at least 8 characters and at most 32 UTF-8 bytes.');
    }
    if (!password) throw new Error('Enter the PDF password.');
    take('password');
  }
  return settings;
}

function PageSelection({ tool, records, options, set, onChange }: { tool: ToolId; records: FileRecord[]; options: Options; set: (key: string, value: Options[string]) => void; onChange: (options: Options) => void }) {
  const id = useId();
  const allowAll = !requirePages.has(tool);
  const kind = !allowAll && options.page_selection === 'all' ? 'range' : options.page_selection;
  const count = records.length > 0 && records.every(({ page_count }) => page_count) ? Math.min(...records.map(({ page_count }) => page_count as number)) : 0;
  const useIndividual = count > 0;
  const selected = String(options.pages).split(',').map(Number);
  const effectiveKind = kind === 'individual' && !useIndividual ? 'range' : kind;

  return <fieldset className="field-group">
    <legend>Pages</legend>
    <select className="field-input" aria-label="Select pages" value={String(effectiveKind)} onChange={(event) => {
      onChange({ ...options, page_selection: event.target.value, pages: '' });
    }}>
      {allowAll && <option value="all">All pages</option>}
      <option value="range">Custom range</option>
      {useIndividual && <option value="individual">Individual pages</option>}
    </select>
    {effectiveKind === 'range' && <div className="field-stack"><label htmlFor={id}>Page numbers and ranges</label><input id={id} className="field-input" value={String(options.pages)} placeholder="1-3, 5, 8" onChange={(event) => set('pages', event.target.value)} /></div>}
    {effectiveKind === 'individual' && <div className="page-picks" aria-label="Page numbers">{Array.from({ length: count }, (_, index) => index + 1).map((page) =>
      <label key={page}><input type="checkbox" aria-label={`Page ${page}`} checked={selected.includes(page)} onChange={(event) => {
        const pages = selected.filter((value) => value > 0 && value !== page);
        if (event.target.checked) pages.push(page);
        set('pages', pages.sort((first, second) => first - second).join(','));
      }} /><span aria-hidden="true">{page}</span></label>,
    )}</div>}
  </fieldset>;
}

export function ConversionSettings({ tool, records, config, options, onChange }: { tool: ToolId; records: FileRecord[]; config: Config; options: Options; onChange: (options: Options) => void }) {
  const id = useId();
  const set = (key: string, value: Options[string]) => onChange({ ...options, [key]: value });
  const word = tool === 'pdf-to-word';
  const ocr = tool === 'ocr-pdf' || (word && options.mode !== 'visual');
  const password = tool === 'protect-pdf' || tool === 'unlock-pdf' || records.some((record) => record.encrypted);
  const canConfigure = pageTools.has(tool) || password || tool === 'compress-pdf';
  if (!canConfigure) return null;

  return <details className="settings" open={!word || password ? true : undefined}>
    <summary><Settings2 size={18} aria-hidden="true" /> {word ? 'Conversion settings' : 'Tool settings'} <ChevronDown size={17} aria-hidden="true" /></summary>
    <div className="settings-body">
      {word && <fieldset className="field-group"><legend>Conversion mode</legend><div className="mode-list">
        {modes.map(([value, label, description]) => <label className="mode-choice" key={value}>
          <input type="radio" name={`${id}-mode`} value={value} checked={options.mode === value} onChange={() => set('mode', value)} />
          <span><strong>{label}</strong><small>{description}</small></span>
        </label>)}
      </div></fieldset>}
      {ocr && <fieldset className="field-group"><legend>Optical character recognition</legend>
        <select className="field-input" aria-label="OCR behavior" value={String(options.ocr)} onChange={(event) => set('ocr', event.target.value)}>
          <option value="auto">Detect scanned pages automatically</option><option value="force">Force OCR on selected pages</option>
          {word && <option value="off">Disable OCR</option>}
        </select>
        {options.ocr !== 'off' && <div className="field-stack"><span className="muted">OCR languages (up to eight)</span><div className="check-grid">
          {config.ocr_languages.map((language) => <label className="check-label" key={language}>
            <input type="checkbox" checked={(options.languages as string[]).includes(language)} disabled={(options.languages as string[]).length >= 8 && !(options.languages as string[]).includes(language)} onChange={(event) => {
              const selected = (options.languages as string[]).filter((entry) => entry !== language);
              if (event.target.checked) selected.push(language);
              set('languages', selected);
            }} />{languageNames[language] ?? language}
          </label>)}
        </div></div>}
      </fieldset>}
      {word && options.mode !== 'visual' && <fieldset className="field-group"><legend>Preserve in Word</legend><div className="check-grid">
        {preserve.map(([key, label]) => <label className="check-label" key={key}><input type="checkbox" checked={Boolean(options[key])} onChange={(event) => set(key, event.target.checked)} />{label}</label>)}
      </div></fieldset>}
      {pageTools.has(tool) && <PageSelection tool={tool} records={records} options={options} set={set} onChange={onChange} />}
      {tool === 'split-pdf' && <label className="field-stack">Split into<select className="field-input" value={String(options.split_mode)} onChange={(event) => set('split_mode', event.target.value)}><option value="pages">One PDF per page</option><option value="ranges">One PDF per range</option></select></label>}
      {tool === 'rotate-pdf' && <label className="field-stack">Clockwise rotation<select className="field-input" value={Number(options.rotation)} onChange={(event) => set('rotation', Number(event.target.value))}>{[90, 180, 270].map((value) => <option key={value} value={value}>{value}°</option>)}</select></label>}
      {tool === 'compress-pdf' && <label className="field-stack">Compression<select className="field-input" value={String(options.compression)} onChange={(event) => set('compression', event.target.value)}><option value="lossless">Lossless</option><option value="balanced">Balanced</option><option value="strong">Strong</option></select></label>}
      {tool === 'pdf-to-jpg' && <label className="field-stack">Image resolution<select className="field-input" value={Number(options.dpi)} onChange={(event) => set('dpi', Number(event.target.value))}><option value={72}>72 DPI</option><option value={150}>150 DPI</option><option value={300}>300 DPI</option></select></label>}
      {tool === 'watermark-pdf' && <label className="field-stack">Watermark text<input className="field-input" maxLength={120} value={String(options.text)} onChange={(event) => set('text', event.target.value)} /></label>}
      {tool === 'page-numbers' && <label className="field-stack">Starting page number<input className="field-input" type="number" min={1} max={1000000} value={String(options.start_number)} onChange={(event) => set('start_number', event.target.value ? Number(event.target.value) : '')} /></label>}
      {password && <label className="field-stack">{tool === 'protect-pdf' ? 'New PDF password' : 'Current PDF password'}<input className="field-input" type="password" autoComplete="off" value={String(options.password)} onChange={(event) => set('password', event.target.value)} /></label>}
    </div>
  </details>;
}
