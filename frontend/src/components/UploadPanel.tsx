import { useRef, useState } from 'react';

export const ACCEPT = '.jpg,.jpeg,.tif,.tiff,.fit,.fits,.fts';

interface UploadPanelProps {
  variant: 'empty' | 'compact';
  onFiles: (files: File[]) => void;
  uploading: boolean;
  onStack?: () => void;
  onSeestar?: () => void;
}

export function UploadPanel({ variant, onFiles, uploading, onStack, onSeestar }: UploadPanelProps) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const hiddenInput = (
    <input
      ref={input}
      type="file"
      multiple
      accept={ACCEPT}
      className="visually-hidden"
      data-testid="file-input"
      aria-label="Choose photo files"
      tabIndex={-1}
      onChange={(e) => {
        const files = Array.from(e.target.files ?? []);
        e.target.value = '';
        if (files.length) onFiles(files);
      }}
    />
  );

  if (variant === 'compact') {
    return (
      <>
        {hiddenInput}
        <button type="button" className="btn" disabled={uploading} onClick={() => input.current?.click()} data-testid="add-files">
          + Add files
        </button>
      </>
    );
  }

  return (
    <section className="empty-state" aria-labelledby="app-title">
      <h1 id="app-title">EasyAstroEnhance</h1>
      <p className="lead">Bring out the detail in your telescope photos.</p>
      <div
        className={over ? 'drop-zone over' : 'drop-zone'}
        data-testid="drop-zone"
        onDragEnter={() => setOver(true)}
        onDragOver={() => setOver(true)}
        onDragLeave={() => setOver(false)}
        onDrop={() => setOver(false)}
      >
        {hiddenInput}
        <p className="drop-title">
          Drop photos here or{' '}
          <button type="button" className="btn primary" disabled={uploading} onClick={() => input.current?.click()}>
            Choose files
          </button>
        </p>
        <p className="helper">JPEG, TIFF, FITS • Multiple files supported • Processed on this computer</p>
      </div>
      {onStack && (
        <p className="helper stack-hint">
          Have a folder of raw sub-frames (for example a Seestar <code>…_sub</code> folder)?{' '}
          <button type="button" className="btn" onClick={onStack} data-testid="stack-button-empty">Stack frames…</button>
        </p>
      )}
      {onSeestar && (
        <p className="helper stack-hint">
          Using a Seestar? <button type="button" className="btn" onClick={onSeestar} data-testid="seestar-button-empty">Import from Seestar…</button>
          {' '}lists your targets and adds the newest stack in one click.
        </p>
      )}
    </section>
  );
}
