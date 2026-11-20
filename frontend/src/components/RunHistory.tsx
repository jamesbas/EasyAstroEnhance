import type { Run } from '../api/types';
import { formatTime } from '../lib/format';

interface RunHistoryProps {
  runs: Run[];
  currentId: string | null;
  onSelect: (id: string) => void;
  // Restores the settings a result was made with (Look, tools, Advanced) into the panel; nothing is reprocessed.
  onUseSettings?: (run: Run) => void;
  sameSettings?: boolean;
}

export function RunHistory({ runs, currentId, onSelect, onUseSettings, sameSettings }: RunHistoryProps) {
  if (runs.length === 0) return null;
  const current = runs.find((r) => r.id === currentId) ?? runs[0];
  return (
    <div className="run-history">
      <label htmlFor="run-select">Compare result</label>
      <select id="run-select" value={current.id} onChange={(e) => onSelect(e.target.value)} data-testid="run-select">
        {runs.map((r, i) => (
          <option key={r.id} value={r.id}>
            Run {r.serial} · {formatTime(r.created_at)}{i === 0 ? ' (latest)' : ''}{r.summary ? ` · ${r.summary}` : ''}
          </option>
        ))}
      </select>
      {onUseSettings && (
        <button type="button" className="btn small" disabled={sameSettings} onClick={() => onUseSettings(current)} data-testid="use-run-settings"
          title={sameSettings ? 'The panel already has the settings of this result.' : `Put the settings of Run ${current.serial} back into the panel`}>
          Use these settings
        </button>
      )}
    </div>
  );
}
