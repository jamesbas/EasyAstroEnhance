import type { Asset } from '../api/types';

// Shown under the viewer for images made with "Stack frames…": what went in and what was skipped (with reasons).
export function StackInfo({ asset }: { asset: Asset }) {
  const s = asset.stack;
  if (!s) return null;
  const c = s.calibration;
  const cal = [c.darks && `${c.darks} darks`, c.flats && `${c.flats} flats`, c.bias && `${c.bias} bias`, c.dark_flats && `${c.dark_flats} dark-flats`].filter(Boolean);
  const exposure = s.total_exposure_s ? ` · ${(s.total_exposure_s / 60).toFixed(1)} min total exposure` : '';
  return (
    <details className="manage stack-info" data-testid="stack-info">
      <summary>
        Stacked {s.frames_used} of {s.frames_total} {s.mode === 'sessions' ? 'stacked images' : s.mode === 'video' ? 'video frames (sharpest)' : 'frames'}{exposure}
        {s.drizzle ? ' · 2× drizzle' : ''}{s.mosaic_canvas ? ` · mosaic ${s.mosaic_canvas[0]} × ${s.mosaic_canvas[1]}` : ''}
      </summary>
      {s.saturation_warning && <p className="warn-text small" data-testid="stack-saturation">{s.saturation_warning}</p>}
      <ul className="small">
        {s.mode === 'subs' && <li>Calibration: {cal.length ? cal.join(', ') : 'none'}{s.defective_pixels ? ` · ${s.defective_pixels} hot/cold pixels repaired` : ''}</li>}
        <li>Stacking took {Math.round(s.seconds)} s.</li>
        {s.rejected_frames.map((r) => <li key={r.name}>Skipped {r.name}: {r.reason}</li>)}
      </ul>
    </details>
  );
}
