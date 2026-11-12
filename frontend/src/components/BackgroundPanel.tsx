import { useState } from 'react';
import { api } from '../api/client';
import type { Asset, BackgroundMethod, Recipe, Rect } from '../api/types';
import { useToasts } from '../hooks/useToasts';
import { BACKGROUND_STRENGTH } from '../lib/recipe';
import type { BgDraft, ViewerTool } from '../types/ui';
import { BackgroundResult } from './BackgroundResult';

const MIN_SAMPLES: Record<BackgroundMethod, number> = { constant: 3, planar: 6 };

interface BackgroundPanelProps {
  asset: Asset;
  recipe: Recipe;
  draft: BgDraft;
  tool: ViewerTool;
  pendingNames: string[];
  edit: (mutate: (r: Recipe) => void) => void;
  patchDraft: (fn: (d: BgDraft) => BgDraft) => void;
  onTool: (t: ViewerTool) => void;
  onAssetUpdated: (a: Asset) => void;
}

function rectText(r: Rect): string {
  return `x ${r.x}, y ${r.y}, ${r.w}×${r.h}`;
}

export function BackgroundPanel(p: BackgroundPanelProps) {
  const { asset, recipe, draft } = p;
  const toasts = useToasts();
  const [busy, setBusy] = useState<'suggest' | 'check' | 'apply' | 'skip' | null>(null);
  const method = recipe.background.method;
  const strength = recipe.advanced.background_strength ?? BACKGROUND_STRENGTH[recipe.background.strength];
  const included = draft.samples.filter((s) => !s.excluded).map((s) => s.rect);
  const need = MIN_SAMPLES[method];
  const key = JSON.stringify([method, strength, included]);
  const checkFresh = draft.check !== null && draft.checkKey === key;
  const canApply = checkFresh && draft.check !== null && draft.check.model.ok && included.length >= need;
  const confirmed = asset.background?.confirmed && asset.background.method === method;

  const suggest = async () => {
    setBusy('suggest');
    try {
      const res = await api.suggestBackground(asset.id);
      p.patchDraft((d) => ({ ...d, suggestions: res.patches, suggestNote: res.note }));
      if (res.patches.length === 0) toasts.notify('info', 'No candidate sky regions were found. Draw regions on the image yourself, or skip background balancing.');
    } catch (err) {
      toasts.error(err);
    } finally {
      setBusy(null);
    }
  };

  const check = async () => {
    setBusy('check');
    try {
      const res = await api.previewBackground(asset.id, { method, samples: included, strength });
      p.patchDraft((d) => ({ ...d, check: res, checkKey: key }));
    } catch (err) {
      toasts.error(err);
    } finally {
      setBusy(null);
    }
  };

  const apply = async () => {
    setBusy('apply');
    try {
      const updated = await api.confirmBackground(asset.id, { method, samples: included, strength, confirmed: true });
      p.onAssetUpdated(updated);
      toasts.notify('success', 'Background correction confirmed for this image.');
    } catch (err) {
      toasts.error(err);
    } finally {
      setBusy(null);
    }
  };

  const skip = async () => {
    setBusy('skip');
    try {
      if (asset.background) p.onAssetUpdated(await api.confirmBackground(asset.id, { method, samples: [], strength, confirmed: false }));
      p.patchDraft((d) => ({ ...d, check: null, checkKey: null }));
      p.edit((r) => { r.background.enabled = false; });
      p.onTool('none');
    } catch (err) {
      toasts.error(err);
    } finally {
      setBusy(null);
    }
  };

  const accept = (r: Rect) => p.patchDraft((d) => ({
    ...d,
    samples: [...d.samples, { rect: r, excluded: false }],
    suggestions: d.suggestions.filter((s) => s !== r),
  }));

  return (
    <div className="bg-panel" data-testid="background-panel">
      <div className="radio-group" role="radiogroup" aria-label="Background model">
        <label className={method === 'constant' ? 'radio active' : 'radio'}>
          <input type="radio" name="bg-method" checked={method === 'constant'} onChange={() => p.edit((r) => { r.background.method = 'constant'; })} />
          <span><strong>Overall balance</strong><small>Removes an even color cast from the whole sky. Needs at least 3 sky regions.</small></span>
        </label>
        <label className={method === 'planar' ? 'radio active' : 'radio'}>
          <input type="radio" name="bg-method" checked={method === 'planar'} onChange={() => p.edit((r) => { r.background.method = 'planar'; })} />
          <span><strong>Uneven sky (gradient)</strong><small>Also flattens a smooth brightness slope across the frame. Needs at least 6 regions spread across the image.</small></span>
        </label>
      </div>

      <button type="button" className="btn prominent" disabled={busy !== null} onClick={() => void skip()} data-testid="skip-background">
        Skip background balancing
      </button>
      <p className="muted small">Skip it when a galaxy or nebula fills the frame and there is no empty sky.</p>

      {asset.status === 'ready' ? (
        <>
          <p className="status-line" data-testid="bg-status">
            {confirmed
              ? `Confirmed for this image: ${method === 'constant' ? 'overall balance' : 'uneven sky'} from ${asset.background?.samples.length ?? 0} regions.`
              : 'Pending: this image has no confirmed sky regions yet, so balancing will be skipped.'}
          </p>
          <div className="row wrap">
            <button type="button" className="btn small" disabled={busy !== null} onClick={() => void suggest()} data-testid="suggest-regions">
              {busy === 'suggest' ? 'Looking…' : 'Suggest regions'}
            </button>
            <button type="button" className={p.tool === 'samples' ? 'btn small active' : 'btn small'} aria-pressed={p.tool === 'samples'} onClick={() => p.onTool(p.tool === 'samples' ? 'none' : 'samples')} data-testid="draw-regions">
              {p.tool === 'samples' ? 'Stop drawing' : 'Draw regions on image'}
            </button>
          </div>
          <p className="muted small">Suggestions are heuristic and need your confirmation. Dark corners alone are not proof of empty sky.</p>

          {draft.suggestions.length > 0 && (
            <div className="sample-block" data-testid="suggestions">
              <div className="row between">
                <strong>Suggested regions</strong>
                <span className="row">
                  <button type="button" className="btn tiny" onClick={() => p.patchDraft((d) => ({ ...d, samples: [...d.samples, ...d.suggestions.map((r) => ({ rect: r, excluded: false }))], suggestions: [] }))}>Accept all</button>
                  <button type="button" className="btn tiny" onClick={() => p.patchDraft((d) => ({ ...d, suggestions: [] }))}>Dismiss</button>
                </span>
              </div>
              {draft.suggestNote && <p className="muted small">{draft.suggestNote}</p>}
              <ul className="sample-list">
                {draft.suggestions.map((r, i) => (
                  <li key={i}><span>{i + 1}. {rectText(r)}</span><button type="button" className="btn tiny" onClick={() => accept(r)}>Accept</button></li>
                ))}
              </ul>
            </div>
          )}

          <div className="sample-block">
            <div className="row between">
              <strong>Sky regions ({included.length} of at least {need})</strong>
              {draft.samples.length > 0 && <button type="button" className="btn tiny" onClick={() => p.patchDraft((d) => ({ ...d, samples: [] }))}>Clear</button>}
            </div>
            {draft.samples.length === 0 ? (
              <p className="muted small">No regions yet. Use Suggest regions or draw rectangles on the original image.</p>
            ) : (
              <ul className="sample-list" data-testid="sample-list">
                {draft.samples.map((s, i) => (
                  <li key={i} className={s.excluded ? 'excluded' : undefined}>
                    <span>{i + 1}. {rectText(s.rect)}{s.excluded ? ' (excluded)' : ''}</span>
                    <span className="row">
                      <button type="button" className="btn tiny" onClick={() => p.patchDraft((d) => ({ ...d, samples: d.samples.map((x, j) => (j === i ? { ...x, excluded: !x.excluded } : x)) }))}>
                        {s.excluded ? 'Include' : 'Exclude'}
                      </button>
                      <button type="button" className="btn tiny" onClick={() => p.patchDraft((d) => ({ ...d, samples: d.samples.filter((_, j) => j !== i) }))}>Remove</button>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {method === 'planar' && <p className="muted small">For the gradient model, spread regions across all corners and edges of the frame.</p>}
          </div>

          <div className="row wrap">
            <button type="button" className="btn small" disabled={busy !== null || included.length < need} onClick={() => void check()} data-testid="check-model">
              {busy === 'check' ? 'Checking…' : 'Check model'}
            </button>
            <button type="button" className="btn small primary" disabled={busy !== null || !canApply} onClick={() => void apply()} data-testid="apply-correction">
              Apply correction
            </button>
            <button type="button" className="btn small" disabled={busy !== null} onClick={() => void skip()} data-testid="skip-correction">Skip</button>
          </div>
          {included.length < need && <p className="muted small">Add {need - included.length} more region{need - included.length === 1 ? '' : 's'} to check the model.</p>}
          {draft.check && <BackgroundResult check={draft.check} samples={included} stale={!checkFresh} />}
        </>
      ) : (
        <p className="muted small">Confirm how this image was saved before choosing sky regions.</p>
      )}

      {p.pendingNames.length > 0 && (
        <p className="muted small" data-testid="bg-pending">
          Background balancing is still pending for: {p.pendingNames.join(', ')}. Each image needs its own confirmed regions; they are never copied between images.
        </p>
      )}
    </div>
  );
}
