import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { Asset, Recipe, Rect, StarMaskResult } from '../api/types';
import { useToasts } from '../hooks/useToasts';
import { ADVANCED_BOUNDS, AUTO_STAGES } from '../lib/recipe';
import type { NumericBound } from '../lib/recipe';
import { Histogram } from './Histogram';

const INTEGER_KEYS = new Set<NumericBound['key']>(['gradient_degree', 'denoise_scales', 'deconvolution_iterations']);

interface StarMaskState {
  on: boolean;
  loading: boolean;
  result: StarMaskResult | null;
  onToggle: (on: boolean) => void;
}

interface AdvancedPanelProps {
  asset: Asset | null;
  recipe: Recipe;
  edit: (mutate: (r: Recipe) => void) => void;
  star: StarMaskState;
  onChangeState: () => void;
  onAssetUpdated: (a: Asset) => void;
}

type Row = { x: string; y: string; w: string; h: string };

const toRow = (r: Rect): Row => ({ x: String(r.x), y: String(r.y), w: String(r.w), h: String(r.h) });

function parseRows(rows: Row[], asset: Asset): { rects: Rect[]; error: string | null } {
  const rects: Rect[] = [];
  for (const [i, r] of rows.entries()) {
    const n = [r.x, r.y, r.w, r.h].map((v) => (v.trim() === '' ? NaN : Number(v)));
    if (n.some((v) => !Number.isInteger(v))) return { rects, error: `Rectangle ${i + 1}: use whole numbers for x, y, width and height.` };
    const [x, y, w, h] = n;
    if (x < 0 || y < 0 || w < 1 || h < 1) return { rects, error: `Rectangle ${i + 1}: width and height must be at least 1 and the corner cannot be negative.` };
    if (asset.width !== null && x + w > asset.width) return { rects, error: `Rectangle ${i + 1} extends past the right edge (${asset.width} px wide).` };
    if (asset.height !== null && y + h > asset.height) return { rects, error: `Rectangle ${i + 1} extends past the bottom edge (${asset.height} px tall).` };
    rects.push({ x, y, w, h });
  }
  return { rects, error: null };
}

function ProtectedRects({ asset, onAssetUpdated }: { asset: Asset; onAssetUpdated: (a: Asset) => void }) {
  const toasts = useToasts();
  const serverKey = JSON.stringify(asset.regions);
  const [rows, setRows] = useState<Row[]>(() => asset.regions.map(toRow));
  const [busy, setBusy] = useState(false);

  useEffect(() => setRows(asset.regions.map(toRow)), [asset.id, serverKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const { rects, error } = parseRows(rows, asset);
  const dirty = JSON.stringify(rects) !== serverKey || rows.length !== asset.regions.length;

  const save = async () => {
    if (error) return;
    setBusy(true);
    try {
      onAssetUpdated(await api.setRegions(asset.id, rects));
    } catch (err) {
      toasts.error(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="adv-block">
      <h4>Protected rectangles</h4>
      <p className="muted small">Areas left untouched (captions, borders). They belong to this image only. Needs &ldquo;Preserve labels&rdquo; on.</p>
      {rows.map((r, i) => (
        <div className="rect-row" key={i}>
          {(['x', 'y', 'w', 'h'] as const).map((k) => (
            <label key={k}>
              <span>{k === 'w' ? 'width' : k === 'h' ? 'height' : k}</span>
              <input type="number" className="num" min={0} step={1} value={r[k]} onChange={(e) => setRows((prev) => prev.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)))} />
            </label>
          ))}
          <button type="button" className="btn tiny" onClick={() => setRows((prev) => prev.filter((_, j) => j !== i))} aria-label={`Remove rectangle ${i + 1}`}>Remove</button>
        </div>
      ))}
      {error && <p className="err-text small">{error}</p>}
      <div className="row">
        <button type="button" className="btn small" disabled={rows.length >= 32} onClick={() => setRows((prev) => [...prev, { x: '0', y: '0', w: '100', h: '100' }])}>Add rectangle</button>
        <button type="button" className="btn small primary" disabled={busy || !dirty || error !== null} onClick={() => void save()}>Save rectangles</button>
      </div>
    </div>
  );
}

function stateText(asset: Asset): string {
  const s = asset.resolved?.state ?? asset.interpretation.state;
  if (s === 'linear') return 'Linear stack';
  if (s === 'rendered') return 'Already processed';
  if (s === 'unsure') return "Not confirmed (preview only)";
  return 'Not confirmed';
}

export function AdvancedPanel({ asset, recipe, edit, star, onChangeState, onAssetUpdated }: AdvancedPanelProps) {
  const setAdv = (key: NumericBound['key'], raw: string, min: number, max: number) => {
    const n = raw.trim() === '' ? null : Number(raw);
    edit((r) => {
      if (n === null || !Number.isFinite(n)) {
        r.advanced[key] = null;
        return;
      }
      const v = Math.min(max, Math.max(min, n));
      r.advanced[key] = INTEGER_KEYS.has(key) ? Math.round(v) : v;
    });
  };
  const anyAdvanced = ADVANCED_BOUNDS.some((b) => recipe.advanced[b.key] !== null);

  return (
    <details className="disclosure" data-testid="advanced-disclosure">
      <summary>Advanced</summary>
      <div className="disclosure-body">
        <div className="adv-block">
          <h4>Automatic steps</h4>
          <p className="muted small">Each step measures the image and runs, or is skipped with a reason in the processing report.</p>
          <label className="check small">
            <input type="checkbox" checked={recipe.tone.enabled} onChange={(e) => edit((r) => { r.tone.enabled = e.target.checked; })} data-testid="auto-stretch" />
            Stretch (automatic, hyperbolic with protected highlights)
          </label>
          {AUTO_STAGES.map((s) => (
            <label key={s.key} className="check small" title={s.hint}>
              <input type="checkbox" checked={recipe.auto[s.key]} onChange={(e) => edit((r) => { r.auto[s.key] = e.target.checked; })} data-testid={`auto-${s.key}`} />
              {s.label} <span className="muted">— {s.hint}</span>
            </label>
          ))}
          <label className="check small">
            <input type="checkbox" checked={recipe.advanced.deconvolution} onChange={(e) => edit((r) => { r.advanced.deconvolution = e.target.checked; })} data-testid="auto-deconvolution" />
            Sharpen by deconvolution (experimental, linear stacks; off by default) <span className="muted">— a sharper look is not added resolution</span>
          </label>
        </div>

        {asset && (
          <div className="adv-block">
            <h4>Input state</h4>
            <p className="small">{stateText(asset)}{asset.baseline?.label ? ` · ${asset.baseline.label}` : ''}</p>
            <button type="button" className="btn tiny" onClick={onChangeState}>Change…</button>
          </div>
        )}

        {asset && asset.status === 'ready' && (
          <div className="adv-block">
            <h4>Star mask</h4>
            <label className="check small">
              <input type="checkbox" checked={star.on} disabled={star.loading} onChange={(e) => star.onToggle(e.target.checked)} data-testid="show-star-mask" />
              {star.loading ? 'Finding stars…' : 'Show star mask'}
            </label>
            {star.on && star.result && !star.result.reliable && (
              <p className="muted small" data-testid="star-mask-reason">
                Star protection is not reliable on this image{typeof star.result.stats.reason === 'string' ? `: ${star.result.stats.reason}` : '.'}
              </p>
            )}
          </div>
        )}

        {asset && asset.status === 'ready' && <ProtectedRects asset={asset} onAssetUpdated={onAssetUpdated} />}

        <div className="adv-block">
          <h4>Exact values</h4>
          <p className="muted small">Leave a field empty to let Enhance choose it from the image.</p>
          <div className="adv-grid">
            {ADVANCED_BOUNDS.map((b) => (
              <label key={b.key} className="field">
                <span>{b.label}</span>
                <input
                  type="number"
                  className="num wide"
                  min={b.min}
                  max={b.max}
                  step={b.step}
                  placeholder="auto"
                  value={recipe.advanced[b.key] ?? ''}
                  title={`${b.hint} (${b.min} to ${b.max})`}
                  onChange={(e) => setAdv(b.key, e.target.value, b.min, b.max)}
                />
                <small>{b.min} – {b.max}</small>
              </label>
            ))}
          </div>
          <button type="button" className="btn tiny" disabled={!anyAdvanced} onClick={() => edit((r) => { for (const b of ADVANCED_BOUNDS) r.advanced[b.key] = null; })}>
            Clear exact values
          </button>
        </div>

        <div className="adv-block">
          <h4>Histogram</h4>
          <Histogram histogram={asset?.baseline?.histogram ?? null} blackPoint={recipe.tone.black_point} clipFraction={null} testId="histogram-advanced" />
        </div>
      </div>
    </details>
  );
}
