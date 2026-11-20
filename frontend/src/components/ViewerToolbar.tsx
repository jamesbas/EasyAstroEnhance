import type { ViewerMode } from '../types/ui';

interface ViewerToolbarProps {
  mode: ViewerMode;
  onMode: (m: ViewerMode) => void;
  canCompare: boolean;
  zoomPercent: number;
  onFit: () => void;
  onActual: () => void;
  autoBlink: boolean;
  onAutoBlink: (v: boolean) => void;
  showClipping: boolean;
  onShowClipping: (v: boolean) => void;
  fixedAvailable: boolean;
  fixedMapping: boolean;
  onFixedMapping: (v: boolean) => void;
}

const MODES: { id: ViewerMode; label: string; testId: string }[] = [
  { id: 'divider', label: 'Divider', testId: 'mode-divider' },
  { id: 'side', label: 'Side by side', testId: 'mode-side' },
  { id: 'blink', label: 'Blink', testId: 'mode-blink' },
];

export function ViewerToolbar(p: ViewerToolbarProps) {
  return (
    <div className="viewer-toolbar" role="toolbar" aria-label="Viewer controls">
      <div className="segmented" role="group" aria-label="Comparison mode">
        {MODES.map((m) => (
          <button
            key={m.id}
            type="button"
            className={p.mode === m.id ? 'seg active' : 'seg'}
            aria-pressed={p.mode === m.id}
            disabled={!p.canCompare}
            data-testid={m.testId}
            title={m.id === 'blink' ? 'Blink between original and enhanced (key B)' : undefined}
            onClick={() => p.onMode(m.id)}
          >
            {m.label}
          </button>
        ))}
      </div>
      {p.mode === 'blink' && p.canCompare && (
        <label className="check small">
          <input type="checkbox" checked={p.autoBlink} onChange={(e) => p.onAutoBlink(e.target.checked)} />
          Auto-blink
        </label>
      )}
      <div className="toolbar-spacer" />
      {p.canCompare && (
        <label className="check small">
          <input type="checkbox" checked={p.showClipping} onChange={(e) => p.onShowClipping(e.target.checked)} data-testid="show-clipping" />
          Show clipping
        </label>
      )}
      {p.fixedAvailable && (
        <label className="check small" title="Diagnostic: the processed data shown with the original image's frozen display stretch">
          <input type="checkbox" checked={p.fixedMapping} onChange={(e) => p.onFixedMapping(e.target.checked)} data-testid="fixed-mapping" />
          Original stretch
        </label>
      )}
      <span className="zoom-readout" aria-live="off">{Math.round(p.zoomPercent)}%</span>
      <button type="button" className="btn small" onClick={p.onFit} data-testid="fit-button" title="Fit the whole image in the viewer (key 0)">Fit</button>
      <button type="button" className="btn small" onClick={p.onActual} data-testid="zoom-100-button" title="Show one image pixel per screen pixel (key 1)">100%</button>
    </div>
  );
}
