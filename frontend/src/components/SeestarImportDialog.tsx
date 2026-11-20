import { useEffect, useRef, useState } from 'react';
import { api, readableError } from '../api/client';
import type { Asset, SeestarScan, SeestarTarget } from '../api/types';
import { formatBytes } from '../lib/format';
import { FolderBrowser } from './FolderBrowser';
import { Modal } from './Modal';

interface SeestarImportDialogProps {
  onClose: () => void;
  onImported: (assets: Asset[]) => void;
  /** open the stack dialog for a sub-frame folder or a video, scanned and with automatic enhancement on */
  onStack: (path: string) => void;
}

const KIND_LABEL: Record<SeestarTarget['kind'], string> = {
  'deep-sky': 'Deep sky', mosaic: 'Mosaic', moon: 'Moon', sun: 'Sun', planet: 'Planets',
};

function when(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

function stackText(t: SeestarTarget): string {
  const s = t.newest_stack;
  if (!s) return 'No Seestar stack';
  const parts = [s.frames && `${s.frames} frames`, s.total_exposure_s && `${Math.round(s.total_exposure_s / 60)} min`, s.filter, when(s.taken)];
  return `Newest stack: ${parts.filter(Boolean).join(' · ')}${t.stacks > 1 ? ` (${t.stacks} stacks)` : ''}`;
}

// Import from Seestar (H12): read-only listing of a MyWorks folder by target, newest first.
export function SeestarImportDialog({ onClose, onImported, onStack }: SeestarImportDialogProps) {
  const [scan, setScan] = useState<SeestarScan | null>(null);
  const [path, setPath] = useState('');
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState<string | null>(null);
  const [browsing, setBrowsing] = useState(false);
  const [error, setError] = useState('');
  const typed = useRef(false);

  const load = async (p: string | null) => {
    setBusy(true);
    setError('');
    try {
      const s = await api.scanSeestar(p);
      setScan(s);
      if (s.path && (p !== null || !typed.current)) setPath(s.path);
      if (s.error) setError(s.error);
    } catch (err) {
      setError(readableError(err));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    void load(null);
  }, []);

  const add = async (file: string) => {
    setAdding(file);
    setError('');
    try {
      const res = await api.importPaths([file]);
      const failed = res.assets.find((a) => a.status === 'failed');
      if (failed?.error) setError(failed.error.message);
      onImported(res.assets);
    } catch (err) {
      setError(readableError(err));
    } finally {
      setAdding(null);
    }
  };

  return (
    <Modal title="Import from Seestar" onClose={onClose} testId="seestar-dialog" wide>
      <p className="muted small">
        Lists the targets in your Seestar <code>MyWorks</code> folder (copied from the telescope or synced by the Seestar app), newest first.
        Your files are only read, never changed.
      </p>
      <div className="field">
        <label htmlFor="seestar-path">MyWorks folder</label>
        <div className="row grow-input">
          <input id="seestar-path" type="text" value={path} spellCheck={false} placeholder="D:\Seestar\MyWorks" data-testid="seestar-path"
            onChange={(e) => { typed.current = true; setPath(e.target.value); }} onKeyDown={(e) => { if (e.key === 'Enter' && path.trim()) void load(path.trim()); }} />
          <button type="button" className="btn" disabled={busy} onClick={() => setBrowsing((b) => !b)}>Browse…</button>
          <button type="button" className="btn" disabled={busy || !path.trim()} onClick={() => void load(path.trim())} data-testid="seestar-scan">
            {busy ? 'Reading…' : 'Show targets'}
          </button>
        </div>
        {browsing && <FolderBrowser start={path || null} onClose={() => setBrowsing(false)} onPick={(p) => { setBrowsing(false); setPath(p); void load(p); }} />}
        {scan && !scan.path && (
          <p className="muted small">
            No MyWorks folder was found automatically.{scan.candidates.length > 0 ? ' Possible folders: ' : ' Browse to it or paste its path.'}
            {scan.candidates.map((c) => <button key={c} type="button" className="link-btn" onClick={() => void load(c)}>{c}</button>)}
          </p>
        )}
      </div>
      {error && <p className="err-text small" role="alert">{error}</p>}
      {scan?.path && !busy && scan.targets.length === 0 && !scan.error && <p className="muted small">No Seestar targets were found in this folder.</p>}
      {scan && scan.targets.length > 0 && (
        <ul className="seestar-targets" data-testid="seestar-targets">
          {scan.targets.map((t) => (
            <li key={t.folder} className="seestar-target" data-testid="seestar-target">
              <div>
                <strong>{t.name}</strong> <span className="badge">{KIND_LABEL[t.kind]}</span>
                <p className="muted small">
                  {t.videos.length > 0 && !t.newest_stack ? `${t.videos.length} video${t.videos.length === 1 ? '' : 's'}, newest ${when(t.videos[0].taken)}` : stackText(t)}
                  {t.subs ? ` · ${t.subs.frames} sub-frames saved` : ''}
                </p>
              </div>
              <div className="row">
                {t.newest_stack && (
                  <button type="button" className="btn small primary" disabled={adding !== null} onClick={() => void add(t.newest_stack!.path)}
                    title={t.newest_stack.name} data-testid="seestar-add-stack">
                    {adding === t.newest_stack.path ? 'Adding…' : 'Add newest stack'}
                  </button>
                )}
                {t.subs && (
                  <button type="button" className="btn small" onClick={() => onStack(t.subs!.path)} data-testid="seestar-stack-subs">
                    {t.kind === 'mosaic' ? 'Stack mosaic…' : 'Stack sub-frames…'}
                  </button>
                )}
              </div>
              {t.videos.length > 0 && (
                <details className="manage">
                  <summary>Videos ({t.videos.length})</summary>
                  <ul className="small">
                    {t.videos.slice(0, 12).map((v) => (
                      <li key={v.path} className="row">
                        <span>{v.name} · {formatBytes(v.bytes)} · {when(v.taken)}</span>
                        {/\.avi$/i.test(v.name) ? (
                          <button type="button" className="btn tiny" onClick={() => onStack(v.path)}>Stack video…</button>
                        ) : <span className="muted">Only RAW AVI videos can be stacked.</span>}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="modal-actions">
        <button type="button" className="btn" onClick={onClose}>Close</button>
      </div>
    </Modal>
  );
}
