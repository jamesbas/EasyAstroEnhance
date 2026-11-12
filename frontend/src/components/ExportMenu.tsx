import { useEffect, useRef, useState } from 'react';
import { api, fullMetadataFitsUrl, readableError } from '../api/client';
import type { BatchIncludeKind, Run } from '../api/types';
import { formatBytes } from '../lib/format';

interface ExportMenuProps {
  run: Run | null;
  batchRunIds: string[];
  onError: (err: unknown) => void;
}

const EXTRA_KINDS: { kind: BatchIncludeKind; label: string }[] = [
  { kind: 'tiff', label: '16-bit TIFF' },
  { kind: 'jpeg', label: 'JPEG for sharing' },
  { kind: 'comparison', label: 'Comparison JPEG' },
  { kind: 'fits', label: 'Processed FITS' },
  { kind: 'linear-tiff', label: 'Linear TIFF' },
];

type ZipState = { phase: 'idle' } | { phase: 'building'; done: number; total: number } | { phase: 'error'; message: string };

function triggerDownload(url: string): void {
  const a = document.createElement('a');
  a.href = url;
  a.download = '';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

export function ExportMenu({ run, batchRunIds, onError }: ExportMenuProps) {
  const [open, setOpen] = useState(false);
  const [include, setInclude] = useState<BatchIncludeKind[]>([]);
  const [zip, setZip] = useState<ZipState>({ phase: 'idle' });
  const rootRef = useRef<HTMLDivElement>(null);
  const cancelled = useRef(false);

  useEffect(() => () => { cancelled.current = true; }, []);

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const png = run?.exports.find((e) => e.kind === 'png');
  const others = run?.exports.filter((e) => e.kind !== 'png') ?? [];
  const hasFits = run?.exports.some((e) => e.kind === 'fits') ?? false;

  const downloadAll = async () => {
    setZip({ phase: 'building', done: 0, total: batchRunIds.length });
    try {
      const started = await api.startBatchExport(batchRunIds, include);
      for (let attempt = 0; attempt < 600; attempt++) {
        await new Promise((r) => window.setTimeout(r, 700));
        if (cancelled.current) return;
        const st = await api.getExport(started.id);
        if (st.state === 'ready' && st.download_url) {
          setZip({ phase: 'idle' });
          triggerDownload(st.download_url);
          return;
        }
        if (st.state === 'failed') throw new Error(st.detail?.error?.message ?? 'The ZIP file could not be created.');
        setZip({ phase: 'building', done: st.detail?.done ?? 0, total: st.detail?.total ?? batchRunIds.length });
      }
      throw new Error('Building the ZIP is taking too long. Try again with fewer results.');
    } catch (err) {
      setZip({ phase: 'error', message: readableError(err) });
      onError(err);
    }
  };

  return (
    <div className="export-bar" ref={rootRef}>
      {png && run ? (
        <a className="btn primary" href={png.url} download data-testid="download-png" title={png.label}>Download PNG</a>
      ) : (
        <button type="button" className="btn primary" disabled data-testid="download-png">Download PNG</button>
      )}
      <div className="menu-wrap">
        <button type="button" className="btn" disabled={!run} aria-haspopup="true" aria-expanded={open} onClick={() => setOpen((o) => !o)} data-testid="more-formats">
          More formats ▾
        </button>
        {open && run && (
          <div className="menu" role="group" aria-label="More formats">
            <ul>
              {others.map((e) => (
                <li key={e.kind}>
                  <a href={e.url} download data-testid={`export-${e.kind}`}>
                    <span>{e.label}</span>
                    <small>{formatBytes(e.bytes)}</small>
                  </a>
                </li>
              ))}
              {hasFits && (
                <li className="menu-warn">
                  <a href={fullMetadataFitsUrl(run.id)} download data-testid="export-fits-full">
                    <span>Full-metadata FITS (includes location/observer details)</span>
                  </a>
                  <small>Keeps the original header, which can contain where and by whom the data was taken. Avoid sharing this file publicly.</small>
                </li>
              )}
            </ul>
            <fieldset className="zip-extras">
              <legend>Also include in Download all</legend>
              {EXTRA_KINDS.map((k) => (
                <label key={k.kind} className="check small">
                  <input
                    type="checkbox"
                    checked={include.includes(k.kind)}
                    onChange={(e) => setInclude((prev) => (e.target.checked ? [...prev, k.kind] : prev.filter((x) => x !== k.kind)))}
                  />
                  {k.label}
                </label>
              ))}
              <p className="muted small">The ZIP always has the PNG, report and summary for each result. Formats a result does not have are skipped.</p>
            </fieldset>
          </div>
        )}
      </div>
      <button
        type="button"
        className="btn"
        disabled={batchRunIds.length === 0 || zip.phase === 'building'}
        onClick={() => void downloadAll()}
        data-testid="download-all"
        title="Download a ZIP of the latest completed results"
      >
        Download all ({batchRunIds.length})
      </button>
      {zip.phase === 'building' && (
        <span className="muted small" role="status" data-testid="zip-progress">Preparing ZIP… {zip.total > 0 ? `${zip.done} of ${zip.total} results` : ''}</span>
      )}
      {zip.phase === 'error' && <span className="err-text small" role="alert">{zip.message}</span>}
    </div>
  );
}
