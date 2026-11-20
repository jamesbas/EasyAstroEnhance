import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from 'react';
import { assetImageUrl, clippingOverlayUrl, withQuery, withRoi } from '../api/client';
import type { Asset, Rect, Run } from '../api/types';
import { useDebounced, useElementSize, useHotkey } from '../hooks/useDom';
import { useViewport } from '../hooks/useViewport';
import { clamp } from '../lib/format';
import { MAX_PREVIEW_EDGE, normalizeRect, planTile, previewScaleFor } from '../lib/tiles';
import type { Mark, ViewerMode, ViewerTool } from '../types/ui';
import { Stage } from './Stage';
import { ViewerToolbar } from './ViewerToolbar';

interface CompareViewerProps {
  asset: Asset;
  run: Run | null;
  hasFixedMapping: boolean;
  tool: ViewerTool;
  onToolDone: () => void;
  marks: Mark[];
  onRectDrawn: (r: Rect) => void;
  labelLineY: number | null;
  onLabelLine: (y: number) => void;
  showClipping: boolean;
  onShowClipping: (v: boolean) => void;
  fixedMapping: boolean;
  onFixedMapping: (v: boolean) => void;
  starOverlayUrl: string | null;
  // A ready live preview of the current (unsaved) settings is shown instead of the selected run's result.
  live?: { url: string; hasFixed: boolean } | null;
}

type Gesture =
  | { kind: 'pan'; x: number; y: number }
  | { kind: 'draw'; sx: number; sy: number }
  | { kind: 'label' }
  | { kind: 'pinch'; dist: number };

function paneOf(target: EventTarget | null): HTMLElement | null {
  return target instanceof Element ? (target.closest('.pane') as HTMLElement | null) : null;
}

export function CompareViewer(props: CompareViewerProps) {
  const { asset, run, tool, marks, labelLineY } = props;
  const imgW = asset.width ?? 0;
  const imgH = asset.height ?? 0;
  const canCompare = run !== null;
  const comparing = canCompare && tool === 'none';

  const [mode, setMode] = useState<ViewerMode>('divider');
  const [pct, setPct] = useState(50);
  const [blinkSide, setBlinkSide] = useState<'original' | 'enhanced'>('enhanced');
  const [autoBlink, setAutoBlink] = useState(false);
  const [nativeScale, setNativeScale] = useState(() => previewScaleFor(imgW, imgH));
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [draft, setDraft] = useState<Rect | null>(null);

  const bodyRef = useRef<HTMLDivElement>(null);
  const paneRef = useRef<HTMLDivElement>(null);
  const size = useElementSize(paneRef);
  const vp = useViewport(imgW, imgH, size.w, size.h);
  const { view } = vp;
  const viewRef = useRef(view);
  viewRef.current = view;

  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const gesture = useRef<Gesture | null>(null);
  const drawStart = useRef<{ x: number; y: number } | null>(null);

  const toggleBlink = useCallback(() => {
    if (!canCompare) return;
    setMode((m) => {
      if (m !== 'blink') return 'blink';
      setBlinkSide((s) => (s === 'enhanced' ? 'original' : 'enhanced'));
      return m;
    });
  }, [canCompare]);
  useHotkey('b', toggleBlink, comparing);

  useEffect(() => {
    if (!autoBlink || mode !== 'blink' || !comparing) return undefined;
    const t = window.setInterval(() => setBlinkSide((s) => (s === 'enhanced' ? 'original' : 'enhanced')), 900);
    return () => window.clearInterval(t);
  }, [autoBlink, mode, comparing]);

  // Debounced full-resolution ROI tiles for both sides once zoom reaches the preview's native scale.
  const settled = useDebounced(view, 250);
  const rawTile = useMemo(() => planTile(settled, size.w, size.h, imgW, imgH, nativeScale), [settled, size.w, size.h, imgW, imgH, nativeScale]);
  const tileKey = rawTile ? `${rawTile.x},${rawTile.y},${rawTile.w},${rawTile.h}` : '';
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const tileRect = useMemo(() => rawTile, [tileKey]);

  const baseOriginal = asset.preview_url ? assetImageUrl(asset, asset.preview_url) : '';
  const live = props.live ?? null;
  const enhancedUrl = live ? live.url : run?.preview_url ?? '';
  const hasFixed = live ? live.hasFixed : props.hasFixedMapping;
  const fixedVariant = props.fixedMapping && hasFixed;
  const baseEnhanced = run ? (fixedVariant ? withQuery(enhancedUrl, { variant: 'fixed' }) : enhancedUrl) : '';
  const tileOriginal = tileRect && baseOriginal ? withRoi(baseOriginal, tileRect) : null;
  const tileEnhanced = tileRect && run ? withRoi(enhancedUrl, tileRect, fixedVariant ? { variant: 'fixed' } : undefined) : null;
  const enhancedLabel = live ? 'Live preview (not saved)' : 'Enhanced';

  const originalLabel = asset.baseline?.label ?? 'Original view';
  const downsampled = nativeScale < 0.999;

  const toSource = (clientX: number, clientY: number, pane: HTMLElement) => {
    const r = pane.getBoundingClientRect();
    const v = viewRef.current;
    return { x: (clientX - r.left - v.tx) / v.z, y: (clientY - r.top - v.ty) / v.z, left: r.left, top: r.top };
  };

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest('.divider-handle')) return;
    const pane = paneOf(e.target);
    if (!pane || e.button === 2) return;
    bodyRef.current?.setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      gesture.current = { kind: 'pinch', dist: Math.hypot(a.x - b.x, a.y - b.y) };
      setDraft(null);
      return;
    }
    const panning = e.button === 1 || tool === 'none' || e.shiftKey;
    if (panning) {
      gesture.current = { kind: 'pan', x: e.clientX, y: e.clientY };
      return;
    }
    const p = toSource(e.clientX, e.clientY, pane);
    if (tool === 'samples') {
      gesture.current = { kind: 'draw', sx: p.x, sy: p.y };
      drawStart.current = { x: p.x, y: p.y };
      setDraft(normalizeRect(p.x, p.y, p.x, p.y, imgW, imgH));
    } else if (tool === 'label') {
      gesture.current = { kind: 'label' };
      props.onLabelLine(Math.round(clamp(p.y, 1, imgH - 1)));
    }
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const g = gesture.current;
    if (!g) return;
    if (pointers.current.has(e.pointerId)) pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (g.kind === 'pan') {
      vp.panBy(e.clientX - g.x, e.clientY - g.y);
      gesture.current = { kind: 'pan', x: e.clientX, y: e.clientY };
    } else if (g.kind === 'pinch' && pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      const rect = paneRef.current?.getBoundingClientRect();
      if (rect && g.dist > 0) vp.zoomBy(dist / g.dist, (a.x + b.x) / 2 - rect.left, (a.y + b.y) / 2 - rect.top);
      gesture.current = { kind: 'pinch', dist };
    } else if (g.kind === 'draw' && paneRef.current) {
      const p = toSource(e.clientX, e.clientY, paneRef.current);
      setDraft(normalizeRect(g.sx, g.sy, p.x, p.y, imgW, imgH));
    } else if (g.kind === 'label' && paneRef.current) {
      props.onLabelLine(Math.round(clamp(toSource(e.clientX, e.clientY, paneRef.current).y, 1, imgH - 1)));
    }
  };

  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    pointers.current.delete(e.pointerId);
    const g = gesture.current;
    if (g?.kind === 'draw' && draft && drawStart.current) {
      const slop = 4 / viewRef.current.z;
      if (draft.w > slop && draft.h > slop) props.onRectDrawn(draft);
    }
    setDraft(null);
    drawStart.current = null;
    if (pointers.current.size === 0) gesture.current = null;
    else if (g?.kind === 'pinch') gesture.current = null;
  };

  // Wheel zoom about the cursor needs a non-passive listener.
  const zoomBy = vp.zoomBy;
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return undefined;
    const onWheel = (e: WheelEvent) => {
      const pane = paneOf(e.target);
      if (!pane) return;
      e.preventDefault();
      const r = pane.getBoundingClientRect();
      zoomBy(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [zoomBy]);

  const onBodyKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget) return;
    const cx = size.w / 2;
    const cy = size.h / 2;
    const step = 60;
    switch (e.key) {
      case '+': case '=': vp.zoomBy(1.25, cx, cy); break;
      case '-': vp.zoomBy(0.8, cx, cy); break;
      case '0': vp.fit(); break;
      case '1': vp.actualSize(); break;
      case 'ArrowLeft': vp.panBy(step, 0); break;
      case 'ArrowRight': vp.panBy(-step, 0); break;
      case 'ArrowUp': vp.panBy(0, step); break;
      case 'ArrowDown': vp.panBy(0, -step); break;
      default: return;
    }
    e.preventDefault();
  };

  const onDividerKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    const big = e.shiftKey ? 10 : 2;
    let next = pct;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') next = pct - big;
    else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') next = pct + big;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = 100;
    else if (e.key === 'PageUp') next = pct + 10;
    else if (e.key === 'PageDown') next = pct - 10;
    else return;
    e.preventDefault();
    e.stopPropagation();
    setPct(clamp(next, 0, 100));
  };

  const dragDivider = (e: ReactPointerEvent<HTMLDivElement>) => {
    const pane = paneRef.current;
    if (!pane) return;
    const r = pane.getBoundingClientRect();
    setPct(clamp(((e.clientX - r.left) / r.width) * 100, 0, 100));
  };

  const mapUrls = {
    original: { base: baseOriginal, tile: tileOriginal },
    enhanced: { base: baseEnhanced, tile: tileEnhanced },
  };

  const renderStage = (side: 'original' | 'enhanced') => (
    <Stage
      key={`${side}-${side === 'enhanced' ? baseEnhanced : baseOriginal}`}
      side={side}
      imgW={imgW}
      imgH={imgH}
      view={view}
      baseUrl={mapUrls[side].base}
      tileUrl={mapUrls[side].tile}
      tileRect={tileRect}
      onBaseLoad={
        side === 'original'
          ? (nw) => {
              setNativeScale(Math.min(1, nw / Math.max(imgW, 1)));
              setLoaded(true);
              setFailed(false);
            }
          : undefined
      }
      onBaseError={side === 'original' ? () => setFailed(true) : undefined}
    >
      {side === 'enhanced' && props.showClipping && run && !live && (
        <img className="stage-overlay" src={clippingOverlayUrl(run.id)} alt="" draggable={false} style={{ width: imgW, height: imgH }} />
      )}
      {props.starOverlayUrl && <img className="stage-overlay" src={props.starOverlayUrl} alt="" draggable={false} style={{ width: imgW, height: imgH }} />}
      {side === 'original' && tool !== 'none' && (
        <>
          {marks.map((m, i) => (
            <div key={i} className={`mark mark-${m.kind}`} style={{ left: m.rect.x, top: m.rect.y, width: m.rect.w, height: m.rect.h }}>
              {m.label && <span className="mark-label">{m.label}</span>}
            </div>
          ))}
          {draft && <div className="mark mark-draft" style={{ left: draft.x, top: draft.y, width: draft.w, height: draft.h }} />}
          {tool === 'label' && labelLineY !== null && (
            <>
              <div className="label-band" style={{ left: 0, top: labelLineY, width: imgW, height: Math.max(0, imgH - labelLineY) }} />
              <div className="label-line" style={{ left: 0, top: labelLineY, width: imgW }} />
            </>
          )}
        </>
      )}
    </Stage>
  );

  const showSecondPane = comparing && mode === 'side';
  const dividerMode = comparing && mode === 'divider';
  const blinkMode = comparing && mode === 'blink';
  const enhancedLayer = comparing && (dividerMode || blinkMode);

  return (
    <section className="viewer" aria-label="Image comparison viewer" data-testid="compare-viewer">
      <ViewerToolbar
        mode={mode}
        onMode={setMode}
        canCompare={canCompare}
        zoomPercent={view.z * 100}
        onFit={vp.fit}
        onActual={vp.actualSize}
        autoBlink={autoBlink}
        onAutoBlink={setAutoBlink}
        showClipping={props.showClipping}
        onShowClipping={props.onShowClipping}
        fixedAvailable={hasFixed && canCompare}
        fixedMapping={props.fixedMapping}
        onFixedMapping={props.onFixedMapping}
      />
      {tool !== 'none' && (
        <div className="viewer-banner" role="status">
          <span>
            {tool === 'samples'
              ? 'Drawing sky regions on the original image. Drag to draw a rectangle; hold Shift (or middle mouse) and drag to pan; scroll to zoom.'
              : 'Drag on the original image to place the top edge of the label band; it runs to the bottom of the image.'}
          </span>
          <button type="button" className="btn small" onClick={props.onToolDone}>Done drawing</button>
        </div>
      )}
      {props.fixedMapping && hasFixed && comparing && (
        <div className="viewer-banner diag" role="status">Diagnostic: the processed data shown with the original image's frozen display stretch</div>
      )}
      <div
        ref={bodyRef}
        className={`viewer-body${tool !== 'none' ? ' drawing' : ''}${showSecondPane ? ' two-up' : ''}`}
        tabIndex={0}
        aria-label="Image area. Scroll to zoom, drag to pan. Plus and minus zoom, 0 fits, 1 shows actual size."
        onKeyDown={onBodyKey}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={(e) => {
          if (tool === 'none' && !(e.target as HTMLElement).closest('.divider-handle')) {
            if (vp.fitted) vp.actualSize();
            else vp.fit();
          }
        }}
      >
        <div className="pane" ref={paneRef} data-testid="viewer-pane">
          <div className="layer" hidden={blinkMode && blinkSide === 'enhanced'} aria-hidden={blinkMode && blinkSide === 'enhanced'}>
            {asset.preview_url && renderStage('original')}
          </div>
          {enhancedLayer && (
            <div
              className="layer layer-enhanced"
              hidden={blinkMode && blinkSide === 'original'}
              style={dividerMode ? { clipPath: `inset(0 0 0 ${pct}%)` } : undefined}
            >
              {renderStage('enhanced')}
            </div>
          )}
          {!loaded && !failed && asset.preview_url && <div className="viewer-msg">Loading preview…</div>}
          {failed && <div className="viewer-msg err">The preview could not be loaded.</div>}
          {!asset.preview_url && <div className="viewer-msg">No preview yet.</div>}
          <span className="chip-label left" data-testid="label-original">
            {blinkMode ? (blinkSide === 'enhanced' ? enhancedLabel : originalLabel) : originalLabel}
          </span>
          {dividerMode && <span className={`chip-label right${live ? ' live' : ''}`} data-testid="label-enhanced">{enhancedLabel}</span>}
          {dividerMode && (
            <div className="divider" style={{ left: `${pct}%` }}>
              <div
                className="divider-handle"
                role="slider"
                tabIndex={0}
                aria-label="Comparison divider"
                aria-orientation="horizontal"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(pct)}
                aria-valuetext={`${Math.round(pct)}% of the image shows the original`}
                data-testid="comparison-divider"
                onKeyDown={onDividerKey}
                onPointerDown={(e) => {
                  e.currentTarget.setPointerCapture(e.pointerId);
                  dragDivider(e);
                }}
                onPointerMove={(e) => {
                  if (e.currentTarget.hasPointerCapture(e.pointerId)) dragDivider(e);
                }}
              >
                <span className="grip" aria-hidden="true">‹ ›</span>
              </div>
            </div>
          )}
        </div>
        {showSecondPane && (
          <div className="pane">
            <div className="layer">{renderStage('enhanced')}</div>
            <span className={`chip-label left${live ? ' live' : ''}`}>{enhancedLabel}</span>
          </div>
        )}
      </div>
      <div className="viewer-foot">
        {downsampled && (
          <span data-testid="downsample-note">
            Preview downsampled to {MAX_PREVIEW_EDGE} px — zoom for full-resolution detail
            {tileRect ? ' (showing full-resolution detail)' : ''}
          </span>
        )}
        {asset.baseline?.preview_only && <span className="warn-text">Preview only: confirm how this image was saved to enable enhancing.</span>}
      </div>
    </section>
  );
}
