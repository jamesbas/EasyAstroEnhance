import { useState } from 'react';
import type { MouseEvent } from 'react';
import { assetImageUrl } from '../api/client';
import type { Asset, Recipe } from '../api/types';
import { assetIsActive } from '../hooks/useWorkspace';
import { colorLabel, fileTypeLabel, formatDims } from '../lib/format';
import { backgroundPending } from '../lib/recipe';
import { Modal } from './Modal';

interface ImageQueueProps {
  assets: Asset[];
  selectedIds: string[];
  primaryId: string | null;
  recipe: Recipe | null;
  onSelect: (id: string, mods: { shift: boolean; toggle: boolean }) => void;
  onToggle: (id: string) => void;
  onRemove: (id: string) => Promise<void>;
  onAnswer: (id: string) => void;
  onRetry: (id: string) => void;
  retryBusy: boolean;
}

function statusClass(label: string): string {
  return label.toLowerCase().replace(/\s+/g, '-');
}

function cardError(a: Asset): string | null {
  if (a.status === 'failed') return a.error?.message ?? a.latest_item?.error?.message ?? 'This file could not be read.';
  if (a.latest_item?.state === 'cancelled') return 'Cancelled before this image was processed. Retry to enhance it.';
  if (a.latest_item && (a.latest_item.state === 'failed' || a.latest_item.state === 'interrupted')) {
    return a.latest_item.error?.message ?? (a.latest_item.state === 'interrupted' ? 'Processing was interrupted. You can enhance this image again.' : null);
  }
  return null;
}

function AssetCard(props: {
  asset: Asset;
  selected: boolean;
  primary: boolean;
  pending: boolean;
  canRetry: boolean;
  onRetry: (id: string) => void;
  onSelect: ImageQueueProps['onSelect'];
  onToggle: (id: string) => void;
  onAskRemove: (a: Asset) => void;
  onAnswer: (id: string) => void;
}) {
  const { asset: a } = props;
  const dims = formatDims(a);
  const meta = [dims, colorLabel(a), fileTypeLabel(a)].filter(Boolean).join(' · ');
  const err = cardError(a);
  const busy = assetIsActive(a);
  const notes = a.latest_item?.notes ?? [];
  const click = (e: MouseEvent) => props.onSelect(a.id, { shift: e.shiftKey, toggle: e.ctrlKey || e.metaKey });

  return (
    <li
      className={`asset-card${props.primary ? ' primary' : ''}${props.selected ? ' selected' : ''}${a.status === 'failed' ? ' failed' : ''}`}
      data-testid="asset-card"
      data-asset-id={a.id}
    >
      <label className="card-check">
        <input
          type="checkbox"
          checked={props.selected}
          onChange={() => props.onToggle(a.id)}
          aria-label={`Select ${a.filename}`}
        />
      </label>
      <button type="button" className="card-main" onClick={click} aria-current={props.primary ? 'true' : undefined} aria-label={`Show ${a.filename}`}>
        <span className="thumb">
          {a.thumb_url ? (
            <img src={assetImageUrl(a, a.thumb_url)} alt="" data-testid="asset-thumb" draggable={false} />
          ) : (
            <span className={`thumb-empty${a.status === 'inspecting' ? ' spin' : ''}`} aria-hidden="true">{a.status === 'failed' ? '!' : ''}</span>
          )}
        </span>
        <span className="card-text">
          <span className="card-name" title={a.filename}>{a.filename}</span>
          {meta && <span className="card-meta">{meta}</span>}
          <span className="card-badges">
            <span className={`status status-${statusClass(a.status_label)}`} data-testid="asset-status">{a.status_label}</span>
            {props.pending && <span className="badge warn" title="Background balancing is on, but sky regions are not confirmed for this image yet">Background pending</span>}
          </span>
        </span>
      </button>
      <button
        type="button"
        className="icon-btn remove"
        aria-label={`Remove ${a.filename}`}
        title="Remove from EasyAstroEnhance"
        disabled={busy && a.latest_item?.state === 'running'}
        onClick={() => props.onAskRemove(a)}
      >
        ×
      </button>
      {err && <p className="card-error" role="note">{err}</p>}
      {props.canRetry && (
        <button type="button" className="btn tiny retry" onClick={() => props.onRetry(a.id)} data-testid="retry-button" aria-label={`Retry ${a.filename}`}>
          Retry
        </button>
      )}
      {a.status === 'needs_input' && (
        <p className="card-note">
          {a.questions.length > 0 ? 'This image needs one answer before it can be enhanced.' : a.intake_message ?? 'Confirm how this image was saved.'}{' '}
          <button type="button" className="link" onClick={() => props.onAnswer(a.id)}>
            {a.questions.length > 0 ? 'Answer' : 'Confirm'}
          </button>
        </p>
      )}
      {!busy && notes.length > 0 && (
        <ul className="card-notes">
          {notes.slice(0, 3).map((n, i) => (
            <li key={i}>{n.message}</li>
          ))}
        </ul>
      )}
      {busy && a.latest_item?.stage && <p className="card-note">{a.latest_item.stage}</p>}
    </li>
  );
}

export function ImageQueue(props: ImageQueueProps) {
  const [removing, setRemoving] = useState<Asset | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);

  return (
    <nav className="queue" aria-label="Image queue">
      <ul className="queue-list">
        {props.assets.map((a) => (
          <AssetCard
            key={a.id}
            asset={a}
            selected={props.selectedIds.includes(a.id)}
            primary={props.primaryId === a.id}
            pending={props.recipe !== null && a.status === 'ready' && backgroundPending(props.recipe, a)}
            canRetry={
              !props.retryBusy && a.status === 'ready' && !assetIsActive(a) &&
              a.latest_item !== null && ['failed', 'interrupted', 'cancelled'].includes(a.latest_item.state)
            }
            onRetry={props.onRetry}
            onSelect={props.onSelect}
            onToggle={props.onToggle}
            onAskRemove={setRemoving}
            onAnswer={props.onAnswer}
          />
        ))}
      </ul>
      {removing && (
        <Modal title="Remove this image?" onClose={() => setRemoving(null)} testId="remove-dialog">
          <p>
            <strong>{removing.filename}</strong> and its results will be removed from EasyAstroEnhance.
            Only the app&apos;s own copies are removed; your original file elsewhere on this computer is not touched.
          </p>
          <div className="modal-actions">
            <button type="button" className="btn" onClick={() => setRemoving(null)}>Keep image</button>
            <button
              type="button"
              className="btn danger"
              disabled={removeBusy}
              onClick={async () => {
                setRemoveBusy(true);
                try {
                  await props.onRemove(removing.id);
                } finally {
                  setRemoveBusy(false);
                  setRemoving(null);
                }
              }}
            >
              Remove image
            </button>
          </div>
        </Modal>
      )}
    </nav>
  );
}
