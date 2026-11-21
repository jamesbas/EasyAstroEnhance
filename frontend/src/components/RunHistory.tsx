import { useEffect, useState } from 'react';
import type { Run } from '../api/types';
import { formatTime } from '../lib/format';

interface RunHistoryProps {
  runs: Run[];
  /** the result being compared in the viewer */
  currentId: string | null;
  /** the image's current result (shown on its card, downloaded, in Download all) */
  activeRunId?: string | null;
  onSelect: (id: string) => void;
  // Restores the settings a result was made with (Look, tools, Advanced) into the panel; nothing is reprocessed.
  onUseSettings?: (run: Run) => void;
  sameSettings?: boolean;
  /** go back to this earlier result: it becomes current and its settings are loaded */
  onMakeCurrent?: (run: Run) => void;
  onDelete?: (run: Run) => void;
  busy?: boolean;
}

export function RunHistory({ runs, currentId, activeRunId, onSelect, onUseSettings, sameSettings, onMakeCurrent, onDelete, busy }: RunHistoryProps) {
  const [confirming, setConfirming] = useState<string | null>(null);
  const shown = runs.find((r) => r.id === currentId) ?? runs[0];
  useEffect(() => setConfirming(null), [shown?.id]);
  if (runs.length === 0 || !shown) return null;
  const isActive = shown.id === (activeRunId ?? runs[0].id);
  return (
    <div className="run-history-wrap">
      <div className="run-history">
        <label htmlFor="run-select">Compare result</label>
        <select id="run-select" value={shown.id} onChange={(e) => onSelect(e.target.value)} data-testid="run-select">
          {runs.map((r) => (
            <option key={r.id} value={r.id}>
              Run {r.serial} · {formatTime(r.created_at)}{r.id === (activeRunId ?? runs[0].id) ? ' (current)' : ''}{r.summary ? ` · ${r.summary}` : ''}
            </option>
          ))}
        </select>
        {onMakeCurrent && !isActive && (
          <button type="button" className="btn small primary" disabled={busy} onClick={() => onMakeCurrent(shown)} data-testid="make-current"
            title={`Go back to Run ${shown.serial}: it becomes this image's result (shown, downloaded, in Download all) and its settings are loaded`}>
            Go back to this result
          </button>
        )}
        {onUseSettings && (
          <button type="button" className="btn small" disabled={sameSettings} onClick={() => onUseSettings(shown)} data-testid="use-run-settings"
            title={sameSettings ? 'The panel already has the settings of this result.' : `Put the settings of Run ${shown.serial} back into the panel`}>
            Use these settings
          </button>
        )}
        {onDelete && (
          <button type="button" className="btn small" disabled={busy || confirming === shown.id} onClick={() => setConfirming(shown.id)} data-testid="delete-run"
            title={`Delete Run ${shown.serial}`}>
            Delete…
          </button>
        )}
      </div>
      {onDelete && confirming === shown.id && (
        <div className="confirm-box small" role="alert" data-testid="delete-run-confirm">
          <p>
            Delete Run {shown.serial}? Its images, exports and report are removed. The original and the other results are kept.
            {isActive && runs.length > 1 ? ' The newest remaining result becomes the current one.' : ''}
          </p>
          <div className="row">
            <button type="button" className="btn small" onClick={() => setConfirming(null)}>Keep it</button>
            <button type="button" className="btn small danger" disabled={busy} data-testid="delete-run-yes"
              onClick={() => { setConfirming(null); onDelete(shown); }}>Delete Run {shown.serial}</button>
          </div>
        </div>
      )}
    </div>
  );
}
