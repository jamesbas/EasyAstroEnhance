import { useEffect, useState } from 'react';
import { api, readableError } from '../api/client';
import type { Recipe, Stack, StackGrading, StackPlan } from '../api/types';
import { FolderBrowser } from './FolderBrowser';
import { Modal } from './Modal';

const FOLDER_KEY = 'eae.stack.folder';

interface StackDialogProps {
  recipe: Recipe | null;
  settingsLabel: string;
  presetId: string | null;
  onClose: () => void;
  onStarted: (stack: Stack) => void;
  newKey: () => string;
}

type CalKey = 'darks' | 'flats' | 'bias' | 'darkflats';
const CAL_FIELDS: { key: CalKey; label: string }[] = [
  { key: 'darks', label: 'Darks folder' },
  { key: 'flats', label: 'Flats folder' },
  { key: 'bias', label: 'Bias folder' },
  { key: 'darkflats', label: 'Dark-flats folder' },
];

function minutes(s: number | null | undefined): string {
  if (!s) return '';
  if (s < 120) return `${Math.round(s)} s`;
  const m = s / 60;
  return m < 120 ? `${m.toFixed(m < 10 ? 1 : 0)} min` : `${(m / 60).toFixed(1)} h`;
}

function PlanSummary({ plan }: { plan: StackPlan }) {
  const l = plan.lights;
  const parts: string[] = [];
  if (plan.mode === 'subs') {
    parts.push(`${l.count} sub-frame${l.count === 1 ? '' : 's'}`);
    if (l.exposures?.length) parts.push(`${l.exposures.join(' / ')} s each`);
  } else {
    parts.push(`${l.count} stacked image${l.count === 1 ? '' : 's'} to combine`);
    if (l.sub_frames) parts.push(`${l.sub_frames} sub-frames in total`);
  }
  if (l.total_exposure_s) parts.push(`${minutes(l.total_exposure_s)} total exposure`);
  if (l.instrument) parts.push(l.instrument);
  if (l.width && l.height) parts.push(`${l.width} × ${l.height}`);
  if (l.nights?.length) parts.push(l.nights.length === 1 ? l.nights[0] : `${l.nights.length} nights`);
  const notUsed = [...plan.excluded, ...plan.skipped];
  const cal = plan.calibration;
  const calText = cal ? [cal.dark && `${cal.dark} darks`, cal.flat && `${cal.flat} flats`, cal.bias && `${cal.bias} bias`, cal.darkflat && `${cal.darkflat} dark-flats`].filter(Boolean).join(', ') : '';
  return (
    <div className="stack-summary" data-testid="stack-summary">
      <p><strong>{plan.mode === 'subs' ? 'Stack sub-frames' : 'Combine stacked images (several nights)'}</strong> — {parts.join(' · ')}</p>
      {plan.mode === 'subs' && <p className="muted small">Calibration: {calText || 'none found — hot pixels are still removed automatically'}</p>}
      {notUsed.length > 0 && (
        <details className="manage">
          <summary>{notUsed.length} file{notUsed.length === 1 ? '' : 's'} will not be used</summary>
          <ul className="small">
            {notUsed.slice(0, 50).map((x) => <li key={x.name}>{x.name}: {x.reason}</li>)}
          </ul>
        </details>
      )}
      {plan.warnings.map((w) => <p key={w} className="warn-text small">{w}</p>)}
      {!plan.can_stack && <p className="err-text small">This folder needs at least two light frames of the same target.</p>}
    </div>
  );
}

export function StackDialog({ recipe, settingsLabel, presetId, onClose, onStarted, newKey }: StackDialogProps) {
  const [folder, setFolder] = useState(() => localStorage.getItem(FOLDER_KEY) ?? '');
  const [cal, setCal] = useState<Record<CalKey, string>>({ darks: '', flats: '', bias: '', darkflats: '' });
  const [plan, setPlan] = useState<StackPlan | null>(null);
  const [scanning, setScanning] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scale, setScale] = useState<1 | 2>(1);
  const [grading, setGrading] = useState<StackGrading>('standard');
  const [rejection, setRejection] = useState(true);
  const [autoEnhance, setAutoEnhance] = useState(false);
  const [browsing, setBrowsing] = useState(false);

  // Any change to the folders makes the summary stale.
  useEffect(() => {
    setPlan(null);
  }, [folder, cal]);

  const folders = (f: string = folder) => ({
    folder: f.trim(),
    darks: cal.darks.trim() || null,
    flats: cal.flats.trim() || null,
    bias: cal.bias.trim() || null,
    darkflats: cal.darkflats.trim() || null,
  });

  const scan = async (f: string = folder) => {
    if (!f.trim()) return;
    setScanning(true);
    setError(null);
    try {
      const p = await api.scanStack(folders(f));
      setPlan(p);
      if (!p.drizzle_available) setScale(1);
      localStorage.setItem(FOLDER_KEY, f.trim());
    } catch (err) {
      setError(readableError(err));
    } finally {
      setScanning(false);
    }
  };

  const start = async () => {
    if (!plan?.can_stack) return;
    setStarting(true);
    setError(null);
    try {
      const s = await api.createStack({
        ...folders(),
        request_key: newKey(),
        scale,
        grading,
        rejection: rejection ? 'sigma' : 'none',
        auto_enhance: autoEnhance,
        recipe: autoEnhance ? recipe : null,
        preset_id: autoEnhance ? presetId : null,
      });
      onStarted(s);
    } catch (err) {
      setError(readableError(err));
    } finally {
      setStarting(false);
    }
  };

  const native = plan?.output?.native;
  const drizzle = plan?.output?.drizzle2x;

  return (
    <Modal title="Stack frames" onClose={onClose} testId="stack-dialog" wide>
      <p className="muted small">
        Combine many short exposures into one cleaner image — for example a Seestar <code>…_sub</code> folder — or merge stacked images of the
        same target from several nights. Your files are only read, never changed.
      </p>
      <div className="field">
        <label htmlFor="stack-folder">Folder with your frames</label>
        <div className="row grow-input">
          <input
            id="stack-folder"
            type="text"
            value={folder}
            placeholder="D:\Seestar\MyWorks\M 42_sub"
            spellCheck={false}
            data-testid="stack-folder"
            onChange={(e) => setFolder(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') void scan(); }}
          />
          <button type="button" className="btn" disabled={scanning} onClick={() => setBrowsing((b) => !b)} data-testid="stack-browse">Browse…</button>
          <button type="button" className="btn" disabled={!folder.trim() || scanning} onClick={() => void scan()} data-testid="stack-scan">
            {scanning ? 'Scanning…' : 'Scan folder'}
          </button>
        </div>
        <p className="muted small">Browse to the folder, or paste the full path (in File Explorer: right-click the folder → Copy as path).</p>
        {browsing && (
          <FolderBrowser start={folder || null} onClose={() => setBrowsing(false)}
            onPick={(p) => { setBrowsing(false); setFolder(p); void scan(p); }} />
        )}
      </div>

      <details className="manage">
        <summary>Calibration frames (optional)</summary>
        <p className="muted small">Darks remove sensor glow and hot pixels; flats remove vignetting and dust shadows. Seestar does not save these by default — stacking works without them.</p>
        {CAL_FIELDS.map((f) => (
          <div className="field" key={f.key}>
            <label htmlFor={`stack-${f.key}`}>{f.label}</label>
            <input id={`stack-${f.key}`} type="text" value={cal[f.key]} spellCheck={false} data-testid={`stack-${f.key}`}
              onChange={(e) => setCal((c) => ({ ...c, [f.key]: e.target.value }))} />
          </div>
        ))}
      </details>

      {plan && <PlanSummary plan={plan} />}
      {error && <p className="err-text small" role="alert" data-testid="stack-error">{error}</p>}

      {plan?.can_stack && (
        <>
          <fieldset className="stack-options">
            <legend>Output size</legend>
            <label className="check">
              <input type="radio" name="stack-scale" checked={scale === 1} onChange={() => setScale(1)} data-testid="stack-scale-native" />
              Native{native ? ` (${native[0]} × ${native[1]})` : ''} — recommended
            </label>
            {plan.drizzle_available && drizzle && (
              <label className="check">
                <input type="radio" name="stack-scale" checked={scale === 2} onChange={() => setScale(2)} data-testid="stack-scale-drizzle" />
                2× drizzle ({drizzle[0]} × {drizzle[1]}) — finer detail with many frames (50+); slower, 4× larger file
              </label>
            )}
          </fieldset>

          <details className="manage">
            <summary>Advanced</summary>
            <div className="field">
              <label htmlFor="stack-grading">Skip poor frames (clouds, trailing, blurry stars)</label>
              <select id="stack-grading" value={grading} onChange={(e) => setGrading(e.target.value as StackGrading)} data-testid="stack-grading">
                <option value="off">Off — use every frame that aligns</option>
                <option value="lenient">Lenient</option>
                <option value="standard">Standard</option>
                <option value="strict">Strict</option>
              </select>
            </div>
            <label className="check">
              <input type="checkbox" checked={rejection} onChange={(e) => setRejection(e.target.checked)} data-testid="stack-rejection" />
              Remove satellite and airplane trails (outlier rejection)
            </label>
          </details>

          <label className="check">
            <input type="checkbox" checked={autoEnhance} disabled={!recipe} onChange={(e) => setAutoEnhance(e.target.checked)} data-testid="stack-auto-enhance" />
            Enhance automatically when stacking finishes
          </label>
          <p className="muted small">
            {autoEnhance
              ? `Uses the current enhancement settings (${settingsLabel}). You can still adjust and enhance again afterwards.`
              : 'Leave this off to look at the stacked image and adjust settings before enhancing.'}
          </p>
        </>
      )}

      <div className="modal-actions">
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary" disabled={!plan?.can_stack || starting} onClick={() => void start()} data-testid="stack-start">
          {starting ? 'Starting…' : 'Start stacking'}
        </button>
      </div>
    </Modal>
  );
}
