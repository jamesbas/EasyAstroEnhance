import { useCallback, useEffect, useMemo, useState } from 'react';
import { clamp } from '../lib/format';

export interface View {
  z: number; // screen px per source px
  tx: number;
  ty: number;
}

const MARGIN = 48;
const MAX_ZOOM = 32;

function clampAxis(t: number, imgSize: number, paneSize: number, z: number): number {
  const s = imgSize * z;
  return clamp(t, MARGIN - s, paneSize - MARGIN);
}

// Shared zoom/pan state in source-pixel space; both comparison sides render with this same transform.
export function useViewport(imgW: number, imgH: number, paneW: number, paneH: number) {
  const [view, setView] = useState<View>({ z: 1, tx: 0, ty: 0 });
  const [fitted, setFitted] = useState(true);

  const fitZoom = useMemo(() => (imgW && imgH && paneW && paneH ? Math.min(paneW / imgW, paneH / imgH) : 1), [imgW, imgH, paneW, paneH]);

  const fitView = useCallback(
    (): View => ({ z: fitZoom, tx: (paneW - imgW * fitZoom) / 2, ty: (paneH - imgH * fitZoom) / 2 }),
    [fitZoom, paneW, paneH, imgW, imgH],
  );

  useEffect(() => {
    if (fitted && paneW > 0 && imgW > 0) setView(fitView());
  }, [fitted, fitView, paneW, imgW]);

  const constrain = useCallback(
    (v: View): View => ({ z: v.z, tx: clampAxis(v.tx, imgW, paneW, v.z), ty: clampAxis(v.ty, imgH, paneH, v.z) }),
    [imgW, imgH, paneW, paneH],
  );

  const zoomTo = useCallback(
    (newZ: number, cx: number, cy: number) => {
      setFitted(false);
      setView((v) => {
        const z = clamp(newZ, Math.min(fitZoom, 1) * 0.5, MAX_ZOOM);
        const k = z / v.z;
        return constrain({ z, tx: cx - (cx - v.tx) * k, ty: cy - (cy - v.ty) * k });
      });
    },
    [constrain, fitZoom],
  );

  const zoomBy = useCallback(
    (factor: number, cx: number, cy: number) => {
      setFitted(false);
      setView((v) => {
        const z = clamp(v.z * factor, Math.min(fitZoom, 1) * 0.5, MAX_ZOOM);
        const k = z / v.z;
        return constrain({ z, tx: cx - (cx - v.tx) * k, ty: cy - (cy - v.ty) * k });
      });
    },
    [constrain, fitZoom],
  );

  const panBy = useCallback(
    (dx: number, dy: number) => {
      setFitted(false);
      setView((v) => constrain({ ...v, tx: v.tx + dx, ty: v.ty + dy }));
    },
    [constrain],
  );

  const fit = useCallback(() => setFitted(true), []);
  const actualSize = useCallback(() => zoomTo(1, paneW / 2, paneH / 2), [zoomTo, paneW, paneH]);

  return { view, fitted, fitZoom, zoomTo, zoomBy, panBy, fit, actualSize };
}
