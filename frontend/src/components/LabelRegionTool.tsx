import { useState } from 'react';
import { api } from '../api/client';
import type { Asset, Rect } from '../api/types';
import { useToasts } from '../hooks/useToasts';
import { clamp } from '../lib/format';
import type { ViewerTool } from '../types/ui';

export function isLabelBand(r: Rect, a: Asset): boolean {
  return a.width !== null && a.height !== null && r.x === 0 && r.w === a.width && r.y + r.h === a.height;
}

interface LabelRegionToolProps {
  asset: Asset;
  tool: ViewerTool;
  lineY: number | null;
  onTool: (t: ViewerTool) => void;
  onLineY: (y: number | null) => void;
  onAssetUpdated: (a: Asset) => void;
}

// Optional, small action: drag one horizontal line to protect a bottom caption band.
export function LabelRegionTool({ asset, tool, lineY, onTool, onLineY, onAssetUpdated }: LabelRegionToolProps) {
  const toasts = useToasts();
  const [busy, setBusy] = useState(false);
  const w = asset.width ?? 0;
  const h = asset.height ?? 0;
  const existing = asset.regions.find((r) => isLabelBand(r, asset));
  const active = tool === 'label';

  const save = async (regions: Rect[]) => {
    setBusy(true);
    try {
      onAssetUpdated(await api.setRegions(asset.id, regions));
      onTool('none');
      onLineY(null);
    } catch (err) {
      toasts.error(err);
    } finally {
      setBusy(false);
    }
  };

  if (asset.status !== 'ready') return null;

  return (
    <div className="label-tool">
      {!active && !existing && (
        <button type="button" className="link" onClick={() => { onLineY(Math.round(h * 0.9)); onTool('label'); }} data-testid="label-start">
          Does this image contain a label?
        </button>
      )}
      {!active && existing && (
        <p className="small">
          Label band protected: bottom {existing.h} px stays untouched.{' '}
          <button type="button" className="link" disabled={busy} onClick={() => void save(asset.regions.filter((r) => r !== existing))}>Remove</button>
        </p>
      )}
      {active && lineY !== null && (
        <div className="label-edit">
          <p className="small">Drag on the image to place the line above your label. Everything below it is left untouched.</p>
          <label className="field inline">
            <span>Line position (px from top)</span>
            <input
              type="number"
              className="num wide"
              min={1}
              max={Math.max(1, h - 1)}
              value={lineY}
              onChange={(e) => onLineY(clamp(Math.round(Number(e.target.value) || 1), 1, Math.max(1, h - 1)))}
            />
          </label>
          <div className="row">
            <button
              type="button"
              className="btn small primary"
              disabled={busy}
              data-testid="label-confirm"
              onClick={() => void save([...asset.regions.filter((r) => !isLabelBand(r, asset)), { x: 0, y: lineY, w, h: h - lineY }])}
            >
              Confirm label region
            </button>
            <button type="button" className="btn small" onClick={() => { onTool('none'); onLineY(null); }}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
