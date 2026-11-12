import type { Run } from '../api/types';
import { formatTime } from '../lib/format';

interface RunHistoryProps {
  runs: Run[];
  currentId: string | null;
  onSelect: (id: string) => void;
}

export function RunHistory({ runs, currentId, onSelect }: RunHistoryProps) {
  if (runs.length === 0) return null;
  return (
    <div className="run-history">
      <label htmlFor="run-select">Compare result</label>
      <select id="run-select" value={currentId ?? runs[0].id} onChange={(e) => onSelect(e.target.value)} data-testid="run-select">
        {runs.map((r, i) => (
          <option key={r.id} value={r.id}>
            Run {r.serial} · {formatTime(r.created_at)}{i === 0 ? ' (latest)' : ''}{r.summary ? ` · ${r.summary}` : ''}
          </option>
        ))}
      </select>
    </div>
  );
}
