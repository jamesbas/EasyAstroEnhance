import { useState } from 'react';
import { api, readableError } from '../api/client';
import type { Asset, MixMode } from '../api/types';
import { Modal } from './Modal';

const MODES: Record<MixMode, { title: string; roles: readonly string[]; rgb?: readonly number[] }> = {
  RGB: { title: 'Broadband RGB', roles: ['Red', 'Green', 'Blue'] },
  LRGB: { title: 'Broadband LRGB', roles: ['Red', 'Green', 'Blue', 'Luminance'] },
  HOO: { title: 'HOO (Ha, OIII)', roles: ['Ha', 'OIII'] },
  SHO: { title: 'SHO (SII, Ha, OIII)', roles: ['SII', 'Ha', 'OIII'] },
  'DUAL-SHO': { title: 'SHO from two dual-band stacks', roles: ['Ha/OIII RGB', 'SII/OIII RGB'], rgb: [0, 1] },
  'HA-RGB': { title: 'Add Ha to broadband RGB', roles: ['Broadband RGB', 'Ha'], rgb: [0] },
};

export function isLinearFits(a: Asset): boolean {
  return a.can_process && a.format === 'fits' && a.baseline?.domain === 'linear';
}

export function ChannelMixDialog({ assets, onClose, onCreated }: {
  assets: Asset[]; onClose: () => void; onCreated: (a: Asset) => void;
}) {
  const [mode, setMode] = useState<MixMode>('RGB');
  const [ids, setIds] = useState<string[]>([]);
  const [gains, setGains] = useState<string[]>([]);
  const [strength, setStrength] = useState(0.5);
  const [prealigned, setPrealigned] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const { roles, rgb } = MODES[mode];
  const eligible = assets.filter(isLinearFits);
  const options = roles.map((_, i) => eligible.filter((a) => a.channel_layout === (rgb?.includes(i) ? 'rgb' : 'mono')));
  const ready = roles.every((_, i) => options[i].some((a) => a.id === ids[i])) && new Set(ids).size === roles.length;

  async function combine() {
    setBusy(true);
    setError('');
    try {
      const a = await api.colorMix({ mode, asset_ids: ids, gains: roles.map((_, i) => Number(gains[i] ?? '1')), strength, prealigned });
      onCreated(a);
    } catch (err) {
      setError(readableError(err));
      setBusy(false);
    }
  }

  return (
    <Modal title="Combine channels" onClose={() => { if (!busy) onClose(); }}>
      <p className="muted small">Add your FITS masters to the queue and confirm they are linear. This creates a new, unstretched RGB master on the first input's grid.</p>
      <form onSubmit={(e) => { e.preventDefault(); if (ready && !busy) void combine(); }}>
        <fieldset disabled={busy}>
          <label className="field">
            <span>Color mix</span>
            <select value={mode} onChange={(e) => {
              const next = (Object.keys(MODES) as MixMode[]).find((key) => key === e.target.value);
              if (!next) return;
              setMode(next); setIds([]); setGains([]); setError('');
            }}>
              {Object.entries(MODES).map(([key, { title }]) => <option key={key} value={key}>{title}</option>)}
            </select>
          </label>
          {roles.map((role, i) => (
            <label className="field" key={role}>
              <span>{role}</span>
              <select value={ids[i] ?? ''} onChange={(e) => {
                const next = [...ids]; next[i] = e.target.value; setIds(next);
              }}>
                <option value="">Select a {rgb?.includes(i) ? 'color' : 'monochrome'} master</option>
                {options[i].map((a) => <option key={a.id} value={a.id} disabled={ids.includes(a.id) && ids[i] !== a.id}>{a.filename}</option>)}
              </select>
            </label>
          ))}
          {mode === 'DUAL-SHO' && <p className="muted small">Uses red from each stack for SII and Ha; OIII is estimated from their green and blue channels.</p>}
          {mode === 'HA-RGB' && <p className="muted small">Lightens red wherever the scaled Ha master is brighter. Match the input scales first.</p>}
          <label className="check"><input type="checkbox" checked={prealigned} onChange={(e) => setPrealigned(e.target.checked)} />
            Unsolved same-size inputs are already aligned
          </label>
          <details className="manage">
            <summary>Channel scales</summary>
            <p className="muted small">Use masters with comparable levels, or set a scale for each channel. Zero points are not changed.</p>
            {roles.map((role, i) => (
              <label className="field" key={role}>
                <span>{role} scale</span>
                <input type="number" min={0.01} max={100} step="any" value={gains[i] ?? '1'} required
                  onChange={(e) => { const next = [...gains]; next[i] = e.target.value; setGains(next); }} />
              </label>
            ))}
            {(mode === 'LRGB' || mode === 'HA-RGB') && (
              <label className="field">
                <span>Blend: {Math.round(strength * 100)}%</span>
                <input type="range" min={0} max={1} step={0.05} value={strength} onChange={(e) => setStrength(Number(e.target.value))} />
              </label>
            )}
          </details>
        </fieldset>
        {error && <p className="err-text small" role="alert">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>Close</button>
          <button type="submit" className="btn primary" disabled={!ready || busy}>{busy ? 'Combining…' : 'Create color master'}</button>
        </div>
      </form>
    </Modal>
  );
}
