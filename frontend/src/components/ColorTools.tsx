import { useEffect, useState } from 'react';
import { api, readableError } from '../api/client';
import type { Asset, ObjectColorRecipe, Recipe } from '../api/types';
import { Switch } from './Controls';
import { SkySolutionPanel } from './SkySolutionPanel';

type Props = {
  asset: Asset | null;
  recipe: Recipe;
  edit: (mutate: (r: Recipe) => void) => void;
  busy: boolean;
  hubbleStrength: number;
  onHubbleStrength: (strength: number) => void;
  onAssetUpdated: (asset: Asset) => void;
  starsReady: boolean;
};
const HUES: { key: keyof ObjectColorRecipe; label: string }[] = [
  { key: 'reds', label: 'Red / orange' },
  { key: 'greens', label: 'Green / teal' },
  { key: 'blues', label: 'Blue / violet' },
];

function useColorPreview(id: string | undefined, { reds, greens, blues }: ObjectColorRecipe, mask: boolean,
  protect: boolean, hubbleStrength = 0) {
  const [preview, setPreview] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState('');

  useEffect(() => {
    if (!id) return;
    const abort = new AbortController();
    let url: string | undefined;
    const timer = setTimeout(() => {
      api.objectColorPreview(id, { reds, greens, blues }, mask, protect, abort.signal, hubbleStrength).then((blob) => {
        if (abort.signal.aborted) return;
        url = URL.createObjectURL(blob);
        setPreview(url);
        setPreviewError('');
      }, (err) => {
        if (!abort.signal.aborted) setPreviewError(readableError(err));
      });
    }, 140);
    return () => {
      clearTimeout(timer);
      abort.abort();
      if (url) URL.revokeObjectURL(url);
      setPreview(null);
      setPreviewError('');
    };
  }, [id, reds, greens, blues, mask, protect, hubbleStrength]);
  return { preview, previewError };
}

const NEUTRAL: ObjectColorRecipe = { reds: 0, greens: 0, blues: 0 };

export function ColorTools({ asset, recipe, edit, busy, hubbleStrength, onHubbleStrength, onAssetUpdated, starsReady }: Props) {
  const [open, setOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [mask, setMask] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [confirmationError, setConfirmationError] = useState('');
  const [catalog, setCatalog] = useState<{ sha256: string; name: string; stars: number } | null>(null);
  const [catalogError, setCatalogError] = useState('');
  const [importing, setImporting] = useState(false);
  const id = asset?.id;
  const colorReady = Boolean(asset?.can_process && asset.channel_layout === 'rgb');
  const linear = asset?.baseline?.domain === 'linear' && asset?.can_process;
  const palette = asset?.hubble_input;
  const catalogReady = linear && colorReady && asset?.format === 'fits' && palette !== 'dualband';
  const editing = Object.values(recipe.object_color).some((amount) => amount !== 0);
  const hue = useColorPreview(open && colorReady && editing ? id : undefined, recipe.object_color, mask, recipe.protect_regions);
  const hubble = useColorPreview(open && paletteOpen && palette === 'dualband' ? id : undefined, NEUTRAL,
    false, recipe.protect_regions, hubbleStrength);

  async function confirmDualband(confirmed: boolean) {
    if (!id) return;
    setConfirming(true);
    setConfirmationError('');
    try {
      onAssetUpdated(await api.setInterpretation(id, { dualband_confirmed: confirmed }));
    } catch (err) {
      setConfirmationError(readableError(err));
    } finally {
      setConfirming(false);
    }
  }

  async function importCatalog(file: File) {
    setImporting(true);
    setCatalogError('');
    try {
      const imported = await api.importCatalog(file);
      setCatalog(imported);
      edit((r) => { r.catalog_sha256 = imported.sha256; r.catalog_builtin = false; });
    } catch (err) {
      setCatalogError(readableError(err));
    } finally {
      setImporting(false);
    }
  }

  return (
    <>
      <details className="manage" onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary>Object Color{editing ? ' (adjusted)' : ''}</summary>
        <p className="muted small">Change one color family at a time. The full-resolution edit protects stars, dark sky and highlights.</p>
        {HUES.map(({ key, label }) => (
          <label className="field" key={key}>
            <span>{label}: {Math.round(recipe.object_color[key] * 100)}%</span>
            <input type="range" min={-1} max={1} step={0.05} value={recipe.object_color[key]} aria-label={label} disabled={!colorReady}
              onChange={(e) => { const v = Number(e.target.value); edit((r) => { r.object_color[key] = v; }); }} />
          </label>
        ))}
        {editing && colorReady && (
          <>
            <label className="check"><input type="checkbox" checked={mask} onChange={(e) => setMask(e.target.checked)} /> Show color mask</label>
            <p className="muted small">Quick preview on the original display. Enhance applies this to the finished image.</p>
            {hue.preview && <img className="object-color-preview" src={hue.preview} alt={mask ? 'Object color mask' : 'Object color preview'} />}
            {hue.previewError && <p className="err-text small" role="alert">{hue.previewError}</p>}
          </>
        )}
        {editing && <button className="btn small" type="button" onClick={() => edit((r) => { r.object_color = { reds: 0, greens: 0, blues: 0 }; })}>Reset object color</button>}
        {(palette === 'dualband' || palette === 'unknown') && (
          <details className="manage" onToggle={(e) => setPaletteOpen(e.currentTarget.open)}>
            <summary>Hubble-style (dual-band)</summary>
            <p className="muted small">Gold and teal from Hα and OIII. No sulfur channel, no CSV. This is a display palette, not SHO.</p>
            {palette === 'unknown' && (
              <>
                <p className="muted small">The FITS doesn't identify a supported filter. Confirm only if this stack was captured with an Hα/OIII dual-band filter.</p>
                <button className="btn small" type="button" disabled={busy || confirming} onClick={() => void confirmDualband(true)}>Confirm Hα/OIII filter</button>
              </>
            )}
            {palette === 'dualband' && (
              <>
                <label className="field">
                  <span>Palette strength: {Math.round(hubbleStrength * 100)}%</span>
                  <input aria-label="Palette strength" type="range" min={0.05} max={1} step={0.05} value={hubbleStrength}
                    onChange={(e) => onHubbleStrength(Number(e.target.value))} />
                </label>
                <p className="muted small">Preview on the original display. Click Enhance Hubble-style for the full result.</p>
                {hubble.preview && <img className="object-color-preview" src={hubble.preview} alt="Hubble-style palette preview" />}
                {hubble.previewError && <p className="err-text small" role="alert">{hubble.previewError}</p>}
                {asset?.interpretation.dualband_confirmed && (
                  <button className="btn small" type="button" disabled={busy || confirming} onClick={() => void confirmDualband(false)}>Clear filter confirmation</button>
                )}
              </>
            )}
            {confirmationError && <p className="err-text small" role="alert">{confirmationError}</p>}
          </details>
        )}
      </details>
      <details className="manage" data-testid="star-colour-tools">
        <summary>Star colour{recipe.catalog_builtin ? ' (accurate)' : recipe.catalog_sha256 ? ' (my catalog)' : ''}</summary>
        <div className={`option-row${recipe.catalog_builtin ? ' on' : ''}`}>
          <div className="option-head">
            <Switch checked={recipe.catalog_builtin} disabled={!catalogReady} label="Accurate star colours" testId="switch-catalog-builtin" describedBy="hint-catalog-builtin"
              onChange={(v) => edit((r) => { r.catalog_builtin = v; if (v) r.catalog_sha256 = null; })} />
          </div>
          <p className="option-hint" id="hint-catalog-builtin">
            Sets the colour balance from the measured colours of catalog stars (Gaia) found in the frame, instead of assuming the average star is white.
            Needs the star catalog and the image’s position on the sky; when either is missing, normal white balance is used and the report says why.
          </p>
          {!catalogReady && <p className="muted small">For linear broadband RGB FITS stacks.</p>}
          {catalogReady && asset && <SkySolutionPanel asset={asset} starsReady={starsReady} onAssetUpdated={onAssetUpdated} />}
        </div>
        <details className="manage">
        <summary>Use my own catalog{recipe.catalog_sha256 ? ' (on)' : ''}</summary>
        <p className="muted small">For solved, unstretched broadband FITS. Import a local CSV with ra_deg, dec_deg, r_over_g and b_over_g. Gaia BP/RP magnitudes are not RGB ratios.</p>
        <label className="field">
          <span>Reference star CSV</span>
          <input type="file" accept=".csv,text/csv" disabled={importing || !catalogReady}
            onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ''; if (file) void importCatalog(file); }} />
        </label>
        {!catalogReady && <p className="muted small">Select a linear broadband RGB FITS to import a catalog.</p>}
        {recipe.catalog_sha256 && (
          <>
            <p className="muted small">{catalog?.sha256 === recipe.catalog_sha256 ? `${catalog.name} (${catalog.stars} stars)` : `Local catalog ${recipe.catalog_sha256.slice(0, 12)}`}. If it can’t match the field, normal white balance remains available.</p>
            <button type="button" className="btn small" onClick={() => edit((r) => { r.catalog_sha256 = null; })}>Use normal white balance</button>
          </>
        )}
        {catalogError && <p className="err-text small" role="alert">{catalogError}</p>}
        </details>
      </details>
      <details className="manage">
        <summary>Stretch method{recipe.focus_stretch.enabled ? ' (focused)' : ''}</summary>
        <label className="field">
          <span>Linear stretch method</span>
          <select disabled={!linear || !recipe.tone.enabled} value={recipe.focus_stretch.enabled ? 'focused' : 'auto'}
            onChange={(e) => { const on = e.target.value === 'focused'; edit((r) => { r.focus_stretch.enabled = on; }); }}>
            <option value="auto">Automatic (recommended)</option>
            <option value="focused">Manual focus</option>
          </select>
        </label>
        {recipe.focus_stretch.enabled && (
          <>
            <p className="muted small">Focus selects where the curve is strongest, from the sky to bright object detail. Enhance to compare it with your previous run.</p>
            {(['strength', 'focus'] as const).map((key) => (
              <label className="field" key={key}>
                <span>{key === 'strength' ? 'Focus strength' : 'Focus position'}: {Math.round(recipe.focus_stretch[key] * 100)}%</span>
                <input type="range" min={0} max={1} step={0.05} value={recipe.focus_stretch[key]} disabled={!linear || !recipe.tone.enabled}
                  onChange={(e) => { const v = Number(e.target.value); edit((r) => { r.focus_stretch[key] = v; }); }} />
              </label>
            ))}
            {(['protect_shadows', 'protect_highlights'] as const).map((key) => (
              <label className="check" key={key}>
                <input type="checkbox" checked={recipe.focus_stretch[key]} disabled={!linear || !recipe.tone.enabled}
                  onChange={(e) => { const v = e.target.checked; edit((r) => { r.focus_stretch[key] = v; }); }} />
                {key === 'protect_shadows' ? 'Protect shadows' : 'Protect highlight color'}
              </label>
            ))}
          </>
        )}
      </details>
    </>
  );
}
