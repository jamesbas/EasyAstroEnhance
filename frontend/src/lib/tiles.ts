import type { Rect } from '../api/types';
import type { View } from '../hooks/useViewport';

export const MAX_PREVIEW_EDGE = 2048;
const SNAP = 32;

export function previewScaleFor(w: number, h: number): number {
  return Math.min(1, MAX_PREVIEW_EDGE / Math.max(w, h, 1));
}

// Plan a full-resolution ROI tile (source pixels) for the visible area when the zoom is at/above the preview's native scale.
// Returns null when the preview already shows everything the screen can resolve.
export function planTile(view: View, paneW: number, paneH: number, imgW: number, imgH: number, previewScale: number): Rect | null {
  if (!paneW || !paneH || !imgW || !imgH) return null;
  if (previewScale >= 0.999 || view.z < previewScale) return null;
  const padX = (paneW / view.z) * 0.1;
  const padY = (paneH / view.z) * 0.1;
  const x0 = Math.max(0, Math.floor((-view.tx / view.z - padX) / SNAP) * SNAP);
  const y0 = Math.max(0, Math.floor((-view.ty / view.z - padY) / SNAP) * SNAP);
  const x1 = Math.min(imgW, Math.ceil(((paneW - view.tx) / view.z + padX) / SNAP) * SNAP);
  const y1 = Math.min(imgH, Math.ceil(((paneH - view.ty) / view.z + padY) / SNAP) * SNAP);
  const w = x1 - x0;
  const h = y1 - y0;
  if (w < 8 || h < 8) return null;
  const tileScale = Math.min(1, MAX_PREVIEW_EDGE / Math.max(w, h));
  if (tileScale <= previewScale * 1.05) return null;
  return { x: x0, y: y0, w, h };
}

export function normalizeRect(ax: number, ay: number, bx: number, by: number, imgW: number, imgH: number): Rect {
  const x0 = Math.max(0, Math.min(ax, bx));
  const y0 = Math.max(0, Math.min(ay, by));
  const x1 = Math.min(imgW, Math.max(ax, bx));
  const y1 = Math.min(imgH, Math.max(ay, by));
  return { x: Math.round(x0), y: Math.round(y0), w: Math.max(1, Math.round(x1 - x0)), h: Math.max(1, Math.round(y1 - y0)) };
}
