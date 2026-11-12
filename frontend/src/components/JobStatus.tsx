import type { Job } from '../api/types';

interface JobStatusProps {
  jobs: Job[];
  cancelling: boolean;
  onCancel: () => void;
}

// Named stages straight from the backend; no invented percentages.
export function JobStatus({ jobs, cancelling, onCancel }: JobStatusProps) {
  const items = jobs.flatMap((j) => j.items.filter((i) => i.state === 'queued' || i.state === 'running'));
  const label = jobs.find((j) => j.processing_label)?.processing_label ?? null;
  if (jobs.length === 0) return <div aria-live="polite" className="job-status empty" data-testid="job-status" />;
  return (
    <div className="job-status" data-testid="job-status" aria-live="polite">
      <div className="row between">
        <strong>Enhancing {items.length} {items.length === 1 ? 'image' : 'images'}</strong>
        {label && <span className="chip small" data-testid="job-device">{label}</span>}
      </div>
      <ul className="job-items">
        {items.map((i) => (
          <li key={i.id}>
            <span className="job-file" title={i.filename ?? undefined}>{i.filename ?? 'Image'}</span>
            <span className="job-stage">{i.state === 'running' ? (i.stage ?? 'Working') : 'Waiting in line'}</span>
          </li>
        ))}
      </ul>
      <button type="button" className="btn small danger" disabled={cancelling} onClick={onCancel} data-testid="cancel-job">
        {cancelling ? 'Cancelling…' : 'Cancel'}
      </button>
      <p className="muted small">Cancelling stops between steps; a step in progress may finish first. Your originals are never changed.</p>
    </div>
  );
}
