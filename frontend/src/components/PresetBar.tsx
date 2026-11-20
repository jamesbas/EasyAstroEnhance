import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../api/client';
import type { Asset, Preset, PresetPreviews, Recipe } from '../api/types';
import { useToasts } from '../hooks/useToasts';
import { cloneRecipe, PRESET_DESCRIPTIONS } from '../lib/recipe';
import { Modal } from './Modal';

// Built-in presets in the order they should be offered (the API lists them alphabetically).
const BUILTIN_ORDER = ['auto', 'natural', 'vivid', 'faint-detail', 'bright-core', 'star-field', 'seestar-match'];
const order = (id: string) => {
  const i = BUILTIN_ORDER.indexOf(id);
  return i < 0 ? BUILTIN_ORDER.length : i;
};

interface PresetBarProps {
  presets: Preset[];
  presetId: string;
  disabled: boolean;
  onSelect: (id: string) => void;
  onSave: (name: string) => Promise<void>;
  onChanged: () => Promise<void>;
  asset?: Asset | null;
  recipe?: Recipe | null;
}

// Quick-look thumbnails of the current image with each built-in preset, rendered on a reduced-size copy. The user's
// other settings (tone, color tools, automatic stages) are kept; the optional AI tools are left out to stay quick.
function PresetPreviewStrip({ asset, recipe, presets, presetId, onSelect }: { asset: Asset; recipe: Recipe; presets: Preset[]; presetId: string; onSelect: (id: string) => void }) {
  const toasts = useToasts();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ assetId: string; data: PresetPreviews } | null>(null);
  useEffect(() => setResult(null), [asset.id]);

  const run = async () => {
    setBusy(true);
    try {
      const items = presets.map((p) => {
        const r = cloneRecipe(p.recipe as Recipe);
        return { id: p.id, recipe: { ...recipe, look: r.look, advanced: { ...recipe.advanced, hdr_amount: r.advanced.hdr_amount, star_stretch_amount: r.advanced.star_stretch_amount },
          auto_preset: r.auto_preset, preset: p.id, ai: { ...recipe.ai, background: false, denoise: false, stars: false } } };
      });
      setResult({ assetId: asset.id, data: await api.presetPreviews(asset.id, items) });
    } catch (err) {
      toasts.error(err);
    } finally {
      setBusy(false);
    }
  };

  const data = result?.assetId === asset.id ? result.data : null;
  return (
    <div className="preset-previews" data-testid="preset-previews">
      {!data && (
        <button type="button" className="btn small" disabled={busy || asset.status !== 'ready'} onClick={() => void run()} data-testid="preview-presets">
          {busy ? 'Making previews…' : 'Preview presets on this image'}
        </button>
      )}
      {data && (
        <>
          <div className="preset-thumbs" role="list">
            {data.items.map((it) => {
              const p = presets.find((x) => x.id === it.id);
              return (
                <button key={it.id} type="button" role="listitem" className={`preset-thumb${it.id === presetId ? ' active' : ''}`}
                  onClick={() => onSelect(it.id)} title={it.summary} data-testid={`preset-thumb-${it.id}`}>
                  <img src={it.url} alt={`${p?.name ?? it.id} preview`} loading="lazy" />
                  <span>{p?.name ?? it.id}{it.auto ? ` → ${it.auto}` : ''}</span>
                </button>
              );
            })}
          </div>
          <p className="muted small">{data.note} Optional AI tools are not included in these quick looks. Click one to use it.</p>
          <div className="row">
            <button type="button" className="btn tiny" disabled={busy} onClick={() => void run()}>{busy ? 'Updating…' : 'Update previews'}</button>
            <button type="button" className="btn tiny" disabled={busy} onClick={() => setResult(null)} data-testid="hide-preset-previews">Hide</button>
          </div>
        </>
      )}
    </div>
  );
}

function SaveDialog({ onSave, onClose }: { onSave: (name: string) => Promise<void>; onClose: () => void }) {
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const toasts = useToasts();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      await onSave(trimmed);
      onClose();
    } catch (err) {
      toasts.error(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Save preset" onClose={onClose} testId="save-preset-dialog">
      <form onSubmit={(e) => void submit(e)} className="stack">
        <p className="muted small">Saves your current enhancement settings (not sky regions or labels, which belong to each image).</p>
        <label className="field">
          <span>Preset name</span>
          <input type="text" value={name} maxLength={60} autoFocus onChange={(e) => setName(e.target.value)} data-testid="preset-name" />
        </label>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary" disabled={busy || !name.trim()} data-testid="confirm-save-preset">Save</button>
        </div>
      </form>
    </Modal>
  );
}

function ManagePopover({ presets, activeId, onChanged, onDeleted }: { presets: Preset[]; activeId: string; onChanged: () => Promise<void>; onDeleted: (id: string) => void }) {
  const toasts = useToasts();
  const mine = presets.filter((p) => !p.builtin);
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const run = async (id: string, action: () => Promise<unknown>) => {
    setBusyId(id);
    try {
      await action();
      await onChanged();
    } catch (err) {
      toasts.error(err);
    } finally {
      setBusyId(null);
    }
  };

  if (mine.length === 0) return <p className="muted small">No saved presets yet. Use Save preset to keep your current settings.</p>;

  return (
    <ul className="preset-manage">
      {mine.map((p) => (
        <li key={p.id}>
          {renaming?.id === p.id ? (
            <form
              className="row"
              onSubmit={(e) => {
                e.preventDefault();
                const name = renaming.name.trim();
                if (name) void run(p.id, () => api.renamePreset(p.id, name)).then(() => setRenaming(null));
              }}
            >
              <input type="text" value={renaming.name} maxLength={60} autoFocus aria-label="New preset name" onChange={(e) => setRenaming({ id: p.id, name: e.target.value })} />
              <button type="submit" className="btn tiny primary" disabled={busyId === p.id}>Rename</button>
              <button type="button" className="btn tiny" onClick={() => setRenaming(null)}>Cancel</button>
            </form>
          ) : (
            <>
              <span className="preset-name">{p.name}{p.id === activeId ? ' (in use)' : ''}</span>
              <span className="row">
                <button type="button" className="btn tiny" disabled={busyId === p.id} onClick={() => setRenaming({ id: p.id, name: p.name })}>Rename</button>
                <button type="button" className="btn tiny" disabled={busyId === p.id} onClick={() => void run(p.id, () => api.duplicatePreset(p.id))}>Duplicate</button>
                <button
                  type="button"
                  className="btn tiny danger"
                  disabled={busyId === p.id}
                  onClick={() => void run(p.id, async () => { await api.deletePreset(p.id); onDeleted(p.id); })}
                >
                  Delete
                </button>
              </span>
            </>
          )}
        </li>
      ))}
    </ul>
  );
}

export function PresetBar(props: PresetBarProps) {
  const [saving, setSaving] = useState(false);
  const builtin = props.presets.filter((p) => p.builtin).sort((a, b) => order(a.id) - order(b.id));
  const user = props.presets.filter((p) => !p.builtin);
  const current = props.presets.find((p) => p.id === props.presetId);

  return (
    <div className="preset-bar">
      <div className="field">
        <label htmlFor="preset-select-el">Preset</label>
        <div className="row grow">
          <select
            id="preset-select-el"
            value={props.presetId}
            disabled={props.disabled}
            data-testid="preset-select"
            onChange={(e) => props.onSelect(e.target.value)}
          >
            {builtin.map((p) => (
              <option key={p.id} value={p.id} disabled={!p.compatible}>{p.name}{p.compatible ? '' : ' (incompatible)'}</option>
            ))}
            <option value="custom">Custom</option>
            {user.length > 0 && (
              <optgroup label="Saved presets">
                {user.map((p) => (
                  <option key={p.id} value={p.id} disabled={!p.compatible} title={p.migration_note ?? undefined}>
                    {p.name}{p.compatible ? '' : ' (incompatible)'}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
          <button type="button" className="btn" disabled={props.disabled} onClick={() => setSaving(true)} data-testid="save-preset">Save preset</button>
        </div>
      </div>
      {props.presets.filter((p) => !p.compatible).map((p) => (
        <p key={p.id} className="muted small warn-text">{p.name}: {p.migration_note}</p>
      ))}
      {current?.builtin && PRESET_DESCRIPTIONS[current.id] && <p className="muted small" data-testid="preset-description">{PRESET_DESCRIPTIONS[current.id]}</p>}
      {props.asset && props.recipe && props.asset.can_process && (
        <PresetPreviewStrip asset={props.asset} recipe={props.recipe} presetId={props.presetId} onSelect={props.onSelect}
          presets={builtin.filter((p) => p.compatible && p.recipe)} />)}
      <details className="manage">
        <summary>Manage presets</summary>
        <ManagePopover presets={props.presets} activeId={props.presetId} onChanged={props.onChanged} onDeleted={(id) => { if (id === props.presetId) props.onSelect('custom'); }} />
      </details>
      {saving && <SaveDialog onSave={props.onSave} onClose={() => setSaving(false)} />}
    </div>
  );
}
