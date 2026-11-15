import type { Asset, Run } from '../api/types';
import { formatTime } from '../lib/format';

interface ResultNoteProps {
  asset: Asset;
  run: Run | null;
}

export function ResultNote({ asset, run }: ResultNoteProps) {
  if (!run) {
    return (
      <div className="result-note muted" data-testid="result-note-empty">
        {asset.status === 'ready' ? 'Pick a preset (or adjust the Look sliders), then press Enhance selected.' : 'Original view only until this image is ready.'}
      </div>
    );
  }
  const itemNotes = asset.latest_item?.run_id === run.id ? asset.latest_item.notes : [];
  const skipped = run.operations.filter((o) => o.status === 'skipped' || o.status === 'reduced');
  return (
    <div className="result-note">
      <p data-testid="result-note"><strong>{run.summary ?? 'Enhancement complete'}</strong></p>
      <p className="muted small">
        Run {run.serial} · {formatTime(run.created_at)}
        {run.backend_label ? ` · ${run.backend_label.replace(/^Processing: /, '')}` : ''}
        {run.seconds !== null ? ` · ${run.seconds.toFixed(1)} s` : ''}
      </p>
      {run.needs_review && <p className="warn-text small">Please review this result: new clipping stayed above the guardrail, so the conservative result was kept.</p>}
      {(itemNotes.length > 0 || skipped.length > 0) && (
        <ul className="notes">
          {itemNotes.map((n, i) => <li key={`n${i}`}>{n.message}</li>)}
          {itemNotes.length === 0 && skipped.map((o, i) => <li key={`s${i}`}>{o.reason ?? `${o.name}: ${o.status}`}</li>)}
        </ul>
      )}
    </div>
  );
}
