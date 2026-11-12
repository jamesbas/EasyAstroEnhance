import { useEffect, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import type { Rect } from '../api/types';
import type { View } from '../hooks/useViewport';

interface TileLayerProps {
  url: string | null;
  rect: Rect | null;
}

// Keeps the previous tile on screen until the next one has finished loading (no flicker while panning).
function TileLayer({ url, rect }: TileLayerProps) {
  const [shown, setShown] = useState<{ url: string; rect: Rect } | null>(null);

  useEffect(() => {
    if (!url || !rect) {
      setShown(null);
      return undefined;
    }
    let cancelled = false;
    const img = new Image();
    img.onload = () => {
      if (!cancelled) setShown({ url, rect });
    };
    img.src = url;
    return () => {
      cancelled = true;
      img.onload = null;
    };
  }, [url, rect]);

  if (!shown) return null;
  return (
    <img
      className="stage-tile"
      src={shown.url}
      alt=""
      draggable={false}
      style={{ left: shown.rect.x, top: shown.rect.y, width: shown.rect.w, height: shown.rect.h }}
    />
  );
}

interface StageProps {
  side: 'original' | 'enhanced';
  imgW: number;
  imgH: number;
  view: View;
  baseUrl: string;
  tileUrl: string | null;
  tileRect: Rect | null;
  onBaseLoad?: (naturalWidth: number) => void;
  onBaseError?: () => void;
  children?: ReactNode;
}

// One side of the comparison: everything is laid out in source-pixel space and moved by the shared CSS transform.
export function Stage({ side, imgW, imgH, view, baseUrl, tileUrl, tileRect, onBaseLoad, onBaseError, children }: StageProps) {
  const style = {
    width: imgW,
    height: imgH,
    transform: `translate(${view.tx}px, ${view.ty}px) scale(${view.z})`,
    '--iz': 1 / view.z,
  } as CSSProperties;
  return (
    <div className={`stage stage-${side}${view.z >= 3 ? ' pixelated' : ''}`} style={style}>
      <img
        className="stage-base"
        src={baseUrl}
        alt=""
        draggable={false}
        style={{ width: imgW, height: imgH }}
        onLoad={(e) => onBaseLoad?.(e.currentTarget.naturalWidth)}
        onError={onBaseError}
      />
      <TileLayer url={tileUrl} rect={tileRect} />
      {children}
    </div>
  );
}
