import { useState } from 'react';
import { api, readableError } from '../api/client';
import type { Asset, SkySolutionSummary } from '../api/types';

interface SkySolutionPanelProps {
  asset: Asset;
  starsReady: boolean;
  onAssetUpdated: (a: Asset) => void;
}

export function skySolved(s: SkySolutionSummary | null | undefined): boolean {
  return s?.status === 'verified' || s?.status === 'solved';
}

function describe(s: SkySolutionSummary | null): string {
  if (!s || s.status === 'none') return 'Not found yet.';
  if (s.status === 'unavailable') return s.reason ?? 'The position on the sky could not be found.';
  const where = [s.center && `centre ${s.center}`, s.scale_arcsec && `${s.scale_arcsec.toFixed(2)}″ per pixel`,
    s.field_deg && `field ${s.field_deg[0].toFixed(2)}° × ${s.field_deg[1].toFixed(2)}°`].filter(Boolean).join(', ');
  const fit = s.matches ? ` ${s.matches} catalog stars matched (${(s.rms_px ?? 0).toFixed(2)} px).` : '';
  return `${s.status === 'verified' ? 'Checked: the file’s own coordinates match the sky' : 'Found'}: ${where}.${fit}`;
}

// Where the image points on the sky (H2): checks a FITS file's WCS or solves it from its pointing, or from a typed name.
export function SkySolutionPanel({ asset, starsReady, onAssetUpdated }: SkySolutionPanelProps) {
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const s = asset.sky_solution;

  async function solve(withName: boolean) {
    setBusy(true);
    setError('');
    try {
      await api.solveSky(asset.id, withName && name.trim() ? { name: name.trim() } : {});
      onAssetUpdated(await api.getAsset(asset.id));
    } catch (err) {
      setError(readableError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="sky-solution" data-testid="sky-solution">
      <p className="small"><strong>Sky position:</strong> <span data-testid="sky-solution-status">{busy ? 'Matching stars… (a few seconds)' : describe(s)}</span></p>
      {!starsReady ? (
        <p className="muted small">Download the star catalog in Settings → Reference data to find where this image points.</p>
      ) : (
        <>
          {!skySolved(s) && (
            <button type="button" className="btn small" disabled={busy || !asset.can_process} onClick={() => void solve(false)} data-testid="sky-solve">
              Find on the sky
            </button>
          )}
          {s?.status === 'unavailable' && (
            <div className="row">
              <input type="text" value={name} maxLength={60} placeholder="Object name, e.g. M 31" aria-label="Object name"
                onChange={(e) => setName(e.target.value)} />
              <button type="button" className="btn small" disabled={busy || !name.trim()} onClick={() => void solve(true)}>Try with this name</button>
            </div>
          )}
        </>
      )}
      {error && <p className="err-text small" role="alert">{error}</p>}
    </div>
  );
}
