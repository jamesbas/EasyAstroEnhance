import { useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent, PointerEvent } from 'react';
import { api, readableError } from '../api/client';
import type { CleanFrame, EditExportBody } from '../api/types';
import { clamp } from '../lib/format';
import { Modal } from './Modal';

const INITIAL_FRAME = { rotation: 0, zoom: 1, pan_x: 0, pan_y: 0 };

// Framing (zoom + pan, no rotation) whose crop window lies inside the clean rectangle, keeping the image's aspect ratio.
// Mirrors backend/app/processing/edit_export.py: window = (W/zoom, H/zoom); left = (W - window) * (pan + 1) / 2.
export function cropToClean(c: CleanFrame): { rotation: number; zoom: number; pan_x: number; pan_y: number } | null {
  if (!c.needed || c.w <= 0 || c.h <= 0) return null;
  const zoom = Math.max(c.width / c.w, c.height / c.h) * 1.004;
  if (zoom > 4) return null;
  const ww = c.width / zoom;
  const wh = c.height / zoom;
  const pan = (start: number, size: number, win: number, total: number) =>
    total - win > 0.5 ? clamp((2 * (start + (size - win) / 2)) / (total - win) - 1, -1, 1) : 0;
  const r = (v: number) => Math.round(v * 1000) / 1000;
  return { rotation: 0, zoom: r(Math.max(1, zoom)), pan_x: r(pan(c.x, c.w, ww, c.width)), pan_y: r(pan(c.y, c.h, wh, c.height)) };
}

export function EditExportDialog({ runId, onClose, cleanFrame = null }: { runId: string; onClose: () => void; cleanFrame?: CleanFrame | null }) {
  const [frame, setFrame] = useState(INITIAL_FRAME);
  const [includeTarget, setIncludeTarget] = useState(false);
  const [target, setTarget] = useState('');
  const [targetHint, setTargetHint] = useState('');
  const [label, setLabel] = useState('');
  const [format, setFormat] = useState<EditExportBody['format']>('png');
  const [preview, setPreview] = useState<{ url: string; request: EditExportBody } | null>(null);
  const [previewError, setPreviewError] = useState<{ request: EditExportBody; message: string } | null>(null);
  const [downloadError, setDownloadError] = useState('');
  const [saving, setSaving] = useState(false);
  const drag = useRef<{ id: number; x: number; y: number; px: number; py: number; w: number; h: number } | null>(null);
  const lookup = useRef(false);
  const userEditedTarget = useRef(false);
  const pendingTarget = includeTarget && !target.trim();
  const cleanCrop = useMemo(() => (cleanFrame ? cropToClean(cleanFrame) : null), [cleanFrame]);
  const previewRequest = useMemo<EditExportBody>(() => ({
    ...frame, target: includeTarget ? target : '', label, format: 'png',
  }), [frame, includeTarget, target, label]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const blob = await api.editExport(runId, previewRequest, true, controller.signal);
        if (!controller.signal.aborted) setPreview({ url: URL.createObjectURL(blob), request: previewRequest });
      } catch (error) {
        if (!controller.signal.aborted) setPreviewError({ request: previewRequest, message: readableError(error) });
      }
    }, 140);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [runId, previewRequest]);

  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview.url);
  }, [preview]);

  const rotate = (angle: number) => setFrame((value) => ({
    ...value, rotation: ((angle % 360 + 540) % 360) - 180, pan_x: 0, pan_y: 0,
  }));
  const onDown = (event: PointerEvent<HTMLImageElement>) => {
    if (frame.zoom <= 1 || event.button !== 0 || drag.current) return;
    const rect = event.currentTarget.getBoundingClientRect();
    drag.current = { id: event.pointerId, x: event.clientX, y: event.clientY, px: frame.pan_x, py: frame.pan_y, w: rect.width, h: rect.height };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onMove = (event: PointerEvent<HTMLImageElement>) => {
    const d = drag.current;
    if (!d || d.id !== event.pointerId || frame.zoom <= 1) return;
    const factor = 2 / (frame.zoom - 1);
    setFrame((value) => ({
      ...value,
      pan_x: clamp(d.px - factor * (event.clientX - d.x) / d.w, -1, 1),
      pan_y: clamp(d.py - factor * (event.clientY - d.y) / d.h, -1, 1),
    }));
  };
  const onKey = (event: KeyboardEvent<HTMLImageElement>) => {
    if (frame.zoom <= 1) return;
    const moves: Record<string, [number, number]> = { ArrowLeft: [-0.1, 0], ArrowRight: [0.1, 0], ArrowUp: [0, -0.1], ArrowDown: [0, 0.1] };
    const move = moves[event.key];
    if (!move) return;
    event.preventDefault();
    setFrame((value) => ({ ...value, pan_x: clamp(value.pan_x + move[0], -1, 1), pan_y: clamp(value.pan_y + move[1], -1, 1) }));
  };
  const toggleTarget = async (on: boolean) => {
    setIncludeTarget(on);
    if (!on || lookup.current) return;
    lookup.current = true;
    setTargetHint('Reading the FITS target name…');
    try {
      const { target: found } = await api.editExportTarget(runId);
      if (found && !userEditedTarget.current) setTarget(found);
      setTargetHint(found ? 'From the FITS header. You can edit it.' : 'No FITS target name found. Type a name to include it.');
    } catch (error) {
      setTargetHint(readableError(error));
    }
  };
  const download = async () => {
    setSaving(true);
    setDownloadError('');
    try {
      const blob = await api.editExport(runId, { ...previewRequest, format }, false);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `EasyAstroEnhance-${runId}-edited.${format === 'png' ? 'png' : 'jpg'}`;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      setDownloadError(readableError(error));
    } finally {
      setSaving(false);
    }
  };
  const previewReady = preview?.request === previewRequest;
  const error = previewError?.request === previewRequest && !previewReady ? previewError.message : null;

  return (
    <Modal title="Edit export" wide onClose={onClose} dismissible={!saving} testId="edit-export-dialog">
      <p className="muted small">Save a new sharing copy of the enhanced image. This won't change your original, regular downloads, or linear data.</p>
      <div className="edit-export-preview" aria-busy={!previewReady && !error}>
        {preview ? (
          <img src={preview.url} alt="Edited export preview" draggable={false} tabIndex={frame.zoom > 1 ? 0 : undefined}
            className={frame.zoom > 1 ? 'pannable' : undefined} aria-describedby="edit-export-framing-help"
            onPointerDown={onDown} onPointerMove={onMove} onLostPointerCapture={() => { drag.current = null; }} onKeyDown={onKey} />
        ) : <span className="muted small">{error ? 'Preview unavailable' : 'Preparing preview…'}</span>}
      </div>
      <p className="muted small" id="edit-export-framing-help">Zoom to crop, then drag the preview or use its arrow keys to frame the image. Angled rotations may leave black corners.</p>
      <fieldset className="edit-export-controls" disabled={saving}>
        <div className="edit-export-buttons">
          <button type="button" className="btn small" onClick={() => rotate(frame.rotation - 90)}>Rotate left 90°</button>
          <button type="button" className="btn small" onClick={() => rotate(frame.rotation + 90)}>Rotate right 90°</button>
          <button type="button" className="btn small" onClick={() => setFrame(INITIAL_FRAME)}>Reset framing</button>
          <button type="button" className="btn small" disabled={!cleanCrop} onClick={() => cleanCrop && setFrame(cleanCrop)} data-testid="crop-stacking-edges"
            title={cleanCrop ? 'Zooms to the largest area without the uneven stacking edges' : cleanFrame?.needed ? 'The clean area is too small to crop to (more than 4× zoom).' : 'No stacking edges were found in this result.'}>
            Crop stacking edges
          </button>
        </div>
        <label>Rotation: {frame.rotation}° <input type="range" aria-label="Rotation" min={-180} max={180} step={1} value={frame.rotation}
          onChange={(e) => setFrame((v) => ({ ...v, rotation: e.target.valueAsNumber, pan_x: 0, pan_y: 0 }))} /></label>
        <label>Zoom: {Math.round(frame.zoom * 100)}% <input type="range" aria-label="Export zoom" min={1} max={4} step={0.05} value={frame.zoom}
          onChange={(e) => {
            const zoom = e.target.valueAsNumber;
            setFrame((v) => zoom === 1 ? { ...v, zoom, pan_x: 0, pan_y: 0 } : { ...v, zoom });
          }} /></label>
        <label>Label text <input type="text" maxLength={120} value={label} placeholder="Your name or company" onChange={(e) => setLabel(e.target.value)} /></label>
        <label className="check"><input type="checkbox" checked={includeTarget} onChange={(e) => void toggleTarget(e.target.checked)} /> Include target name</label>
        {includeTarget && (
          <>
            <label>Target name <input type="text" maxLength={80} value={target} onChange={(e) => { userEditedTarget.current = true; setTarget(e.target.value); }} /></label>
            <p className="muted small" role="status">{targetHint}</p>
          </>
        )}
        <label>Format <select value={format} onChange={(e) => setFormat(e.target.value === 'jpeg' ? 'jpeg' : 'png')}>
          <option value="png">PNG (16-bit)</option>
          <option value="jpeg">JPEG (for sharing)</option>
        </select></label>
      </fieldset>
      {(downloadError || error) && <p className="err-text small" role="alert">{downloadError || error}</p>}
      <div className="modal-actions">
        <button type="button" className="btn" disabled={saving} onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary" disabled={saving || !previewReady || pendingTarget} onClick={() => void download()}>
          {saving ? 'Preparing download…' : 'Download edited image'}
        </button>
      </div>
    </Modal>
  );
}
