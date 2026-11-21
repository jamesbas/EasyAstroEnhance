import type { Asset, Recipe, Run } from '../api/types';
import { formatTime } from '../lib/format';
import { REMOVABLE_STEPS, removableSteps } from '../lib/steps';

interface ResultNoteProps {
  asset: Asset;
  run: Run | null;
  /** the panel settings: steps already turned off there are shown as removed */
  recipe?: Recipe | null;
  /** turn off one step of this result; offered for the image's current result only */
  onRemoveStep?: (name: string) => void;
}

export function ResultNote({ asset, run, recipe, onRemoveStep }: ResultNoteProps) {
  if (!run) {
    return (
      <div className="result-note muted" data-testid="result-note-empty">
        {asset.status === 'ready' ? 'Pick a preset (or adjust the Look sliders), then press Enhance selected.' : 'Original view only until this image is ready.'}
      </div>
    );
  }
  const itemNotes = asset.latest_item?.run_id === run.id ? asset.latest_item.notes : [];
  const skipped = run.operations.filter((o) => o.status === 'skipped' || o.status === 'reduced');
  const steps = onRemoveStep ? removableSteps(run.operations) : [];
  return (
    <div className="result-note">
      <p data-testid="result-note"><strong>{run.summary ?? 'Enhancement complete'}</strong></p>
      <p className="muted small">
        Run {run.serial} · {formatTime(run.created_at)}
        {run.backend_label ? ` · ${run.backend_label.replace(/^Processing: /, '')}` : ''}
        {run.seconds !== null ? ` · ${run.seconds.toFixed(1)} s` : ''}
      </p>
      {run.needs_review && <p className="warn-text small">Please review this result: new clipping stayed above the guardrail, so the conservative result was kept.</p>}
      {steps.length > 0 && onRemoveStep && (
        <div className="step-chips" data-testid="remove-steps">
          <span className="muted small">Remove a step:</span>
          {steps.map((name) => {
            const s = REMOVABLE_STEPS[name];
            const off = recipe ? s.isOff(recipe) : false;
            return (
              <button key={name} type="button" className={`step-chip${off ? ' off' : ''}`} disabled={off} data-testid={`remove-step-${name}`}
                aria-label={off ? `${s.label} (turned off)` : `Remove ${s.label}`}
                title={off ? `Turned off (${s.setting}). Undo or switch it back on to restore it.` : `Turn this step off (${s.setting}) and preview the result without it`}
                onClick={() => onRemoveStep(name)}>
                {s.label} <span aria-hidden="true">{off ? '(off)' : '×'}</span>
              </button>
            );
          })}
        </div>
      )}
      {(itemNotes.length > 0 || skipped.length > 0) && (
        <ul className="notes">
          {itemNotes.map((n, i) => <li key={`n${i}`}>{n.message}</li>)}
          {itemNotes.length === 0 && skipped.map((o, i) => <li key={`s${i}`}>{o.reason ?? `${o.name}: ${o.status}`}</li>)}
        </ul>
      )}
    </div>
  );
}
