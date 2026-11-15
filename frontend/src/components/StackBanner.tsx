import type { Stack } from '../api/types';

interface StackBannerProps {
  stacks: Stack[];
  onCancel: (id: string) => void;
}

export function StackBanner({ stacks, onCancel }: StackBannerProps) {
  if (stacks.length === 0) return null;
  return (
    <>
      {stacks.map((s) => (
        <div key={s.id} className="banner stack-banner" role="status" data-testid="stack-banner">
          <span>
            <strong>{s.state === 'queued' ? 'Waiting to stack' : 'Stacking'} {s.name}</strong>
            {s.state === 'running' && s.stage ? ` — ${s.stage}` : ''}
            {s.auto_enhance ? ' · will enhance when done' : ''}
          </span>
          <span className="row">
            {s.state === 'running' && (
              <progress max={1} value={s.progress ?? undefined} aria-label={`Stacking progress for ${s.name}`} />
            )}
            <button type="button" className="btn small" onClick={() => onCancel(s.id)} data-testid="stack-cancel">Cancel</button>
          </span>
        </div>
      ))}
    </>
  );
}
