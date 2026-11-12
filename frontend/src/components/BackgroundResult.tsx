import type { BackgroundPreview, Rect } from '../api/types';

const LABELS: Record<string, string> = {
  patch_noise_sigma: 'Typical noise in a region',
  channel_spread_rms: 'Color spread between regions',
  condition_number: 'Layout conditioning (lower is better)',
  rms: 'Plane fit residual (rms)',
  max_abs: 'Largest residual',
  amplitude: 'Gradient strength across the frame',
};

function fmt(v: number): string {
  if (v === 0) return '0';
  const a = Math.abs(v);
  return a < 0.001 || a >= 1000 ? v.toExponential(2) : v.toPrecision(3);
}

// Blue (negative) to orange (positive) around zero.
function heatColor(v: number, extent: number): string {
  const t = extent > 0 ? Math.max(-1, Math.min(1, v / extent)) : 0;
  const a = Math.abs(t);
  const base = t < 0 ? [70, 130, 230] : [235, 150, 60];
  const mix = (c: number) => Math.round(30 + (c - 30) * a);
  return `rgb(${mix(base[0])}, ${mix(base[1])}, ${mix(base[2])})`;
}

function PlaneHeatmap({ grid }: { grid: number[][] }) {
  const flat = grid.flat();
  const extent = Math.max(...flat.map((v) => Math.abs(v)), 1e-9);
  const n = grid.length;
  return (
    <figure className="heatmap">
      <svg viewBox={`0 0 ${n} ${n}`} role="img" aria-label="Fitted sky gradient across the frame" preserveAspectRatio="none">
        {grid.map((row, y) => row.map((v, x) => <rect key={`${x}-${y}`} x={x} y={y} width={1.02} height={1.02} fill={heatColor(v, extent)} />))}
      </svg>
      <figcaption>Fitted gradient (colors scaled to its own range, ±{fmt(extent)}). Blue is darker, orange is brighter.</figcaption>
    </figure>
  );
}

interface BackgroundResultProps {
  check: BackgroundPreview;
  samples: Rect[];
  stale: boolean;
}

export function BackgroundResult({ check, samples, stale }: BackgroundResultProps) {
  const { model } = check;
  const errors = model.issues.filter((i) => i.level === 'error');
  const warnings = model.issues.filter((i) => i.level === 'warning');
  const stats = Object.entries(model.residuals)
    .filter(([k, v]) => k in LABELS && typeof v === 'number')
    .map(([k, v]) => [LABELS[k], fmt(v as number)] as const);

  return (
    <div className="bg-result" data-testid="bg-result">
      {stale && <p className="badge warn">Regions or settings changed since this check. Check the model again.</p>}
      <p className={model.ok ? 'ok-text' : 'err-text'}>
        {model.ok ? `The model fits ${samples.length} regions and can be applied.` : 'This set of regions cannot be applied.'}
      </p>
      {errors.length > 0 && (
        <ul className="issues errors" aria-label="Problems that block the correction">
          {errors.map((i, n) => <li key={n}><strong>Problem:</strong> {i.message}</li>)}
        </ul>
      )}
      {warnings.length > 0 && (
        <ul className="issues warnings" aria-label="Warnings">
          {warnings.map((i, n) => <li key={n}><strong>Warning:</strong> {i.message}</li>)}
        </ul>
      )}
      {stats.length > 0 && (
        <dl className="stats">
          {stats.map(([k, v]) => (
            <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
          ))}
        </dl>
      )}
      {check.preview_url && (
        <figure className="bg-preview">
          <img src={check.preview_url} alt="Original image with the proposed background correction applied" />
          <figcaption>Proposed correction (preview)</figcaption>
        </figure>
      )}
      {check.plane_grid && <PlaneHeatmap grid={check.plane_grid} />}
    </div>
  );
}
