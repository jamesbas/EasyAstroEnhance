import { useEffect, useState } from 'react';
import { api, readableError } from '../api/client';
import type { FolderEntry, FolderListing } from '../api/types';

interface FolderBrowserProps {
  start: string | null;
  onPick: (path: string) => void;
  onClose: () => void;
}

function count(e: FolderEntry): string {
  return e.fits > 0 ? `${e.fits >= 9999 ? '9999+' : e.fits} FITS` : '';
}

// Read-only folder picker for stacking: lists subfolders one level at a time with their FITS counts; Seestar
// "…_sub" folders are marked. Nothing is opened except directory listings.
export function FolderBrowser({ start, onPick, onClose }: FolderBrowserProps) {
  const [listing, setListing] = useState<FolderListing | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const open = async (path: string | null) => {
    setLoading(true);
    setError(null);
    try {
      const l = await api.browseFolders(path);
      if (l.error && path) {
        setError(l.error);
        setListing(await api.browseFolders(null));
      } else {
        setListing(l);
      }
    } catch (err) {
      setError(readableError(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void open(start && start.trim() ? start.trim() : null);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const row = (e: FolderEntry, key: string) => (
    <li key={key}>
      <button type="button" className="folder-open" onClick={() => void open(e.path)} title={e.path}>
        {e.name}{e.is_sub && <span className="badge ok" style={{ marginLeft: 6 }}>sub-frames</span>}
      </button>
      <span className="muted small">{count(e)}</span>
      {e.fits > 1 && <button type="button" className="btn tiny primary" onClick={() => onPick(e.path)}>Use</button>}
    </li>
  );

  return (
    <div className="folder-browser" data-testid="folder-browser">
      <div className="row">
        <button type="button" className="btn tiny" disabled={loading || !listing?.path} onClick={() => void open(listing?.parent ?? null)}>Up</button>
        <button type="button" className="btn tiny" disabled={loading} onClick={() => void open(null)}>Drives & recent</button>
        <span className="folder-path grow">{listing?.path ?? 'Choose a drive or a recent folder'}</span>
        <button type="button" className="btn tiny" onClick={onClose}>Close</button>
      </div>
      {error && <p className="warn-text small">{error}</p>}
      {listing?.path && (
        <div className="row">
          <span className="small">{listing.fits > 0 ? `${listing.fits} FITS files in this folder` : 'No FITS files directly in this folder'}</span>
          {listing.fits > 1 && <button type="button" className="btn small primary" onClick={() => onPick(listing.path as string)} data-testid="folder-use-current">Use this folder</button>}
        </div>
      )}
      {!listing?.path && listing && listing.recent.length > 0 && (
        <>
          <p className="small"><strong>Recently stacked</strong></p>
          <ul className="folder-list">{listing.recent.map((e) => row(e, `r-${e.path}`))}</ul>
        </>
      )}
      {!listing?.path && listing && listing.suggestions.length > 0 && (
        <>
          <p className="small"><strong>Other sub-frame folders next to them</strong></p>
          <ul className="folder-list">{listing.suggestions.map((e) => row(e, `s-${e.path}`))}</ul>
        </>
      )}
      {listing && (
        <ul className="folder-list" data-testid="folder-list">
          {listing.folders.length === 0 && <li className="muted small">{loading ? 'Loading…' : 'No subfolders.'}</li>}
          {listing.folders.map((e) => row(e, e.path))}
        </ul>
      )}
      <p className="muted small">Folders are only listed; nothing is opened or changed.</p>
    </div>
  );
}
