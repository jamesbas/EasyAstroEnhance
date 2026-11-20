import { useEffect, useRef, useState } from 'react';
import { api, readableError } from '../api/client';
import type { LivePreview, Recipe } from '../api/types';
import { normalizeRecipe } from '../lib/recipe';

export type LiveStatus = 'off' | 'waiting' | 'working' | 'ready' | 'failed';

export interface LiveResult {
  status: LiveStatus;
  // The newest finished preview for this image (may be for slightly older settings while a newer one is working).
  preview: LivePreview | null;
  // True when `preview` was rendered from exactly the current settings.
  current: boolean;
  error: string | null;
}

const DEBOUNCE_MS = 600;
const POLL_MS = 400;

// Renders the current settings for one image at full resolution without saving anything; the latest request wins and
// the server only recomputes the display stage when the linear settings are unchanged.
export function useLivePreview(assetId: string | null, recipe: Recipe | null, enabled: boolean): LiveResult {
  const key = recipe ? normalizeRecipe(recipe) : '';
  const [state, setState] = useState<{ asset: string | null; status: LiveStatus; preview: LivePreview | null; key: string; error: string | null }>(
    { asset: null, status: 'off', preview: null, key: '', error: null },
  );
  const recipeRef = useRef(recipe);
  recipeRef.current = recipe;

  // Changing image (or turning live preview off) drops the old preview and cancels any pending work for that image.
  useEffect(() => {
    setState({ asset: assetId, status: 'off', preview: null, key: '', error: null });
    if (!assetId) return undefined;
    return () => {
      void api.cancelLivePreview(assetId).catch(() => undefined);
    };
  }, [assetId]);

  useEffect(() => {
    if (!assetId || !enabled || !recipeRef.current) {
      setState((s) => (s.status === 'off' ? s : { ...s, status: 'off' }));
      return undefined;
    }
    let stopped = false;
    let poll: number | undefined;
    setState((s) => ({ ...s, status: 'waiting', error: null }));
    const timer = window.setTimeout(() => {
      const sent = recipeRef.current;
      if (!sent) return;
      const check = async (id: string) => {
        if (stopped) return;
        try {
          const st = await api.livePreview(assetId);
          if (stopped) return;
          if (st.id !== id) return; // replaced by a newer request (another tab or a quick follow-up)
          if (st.state === 'ready') setState({ asset: assetId, status: 'ready', preview: st, key, error: null });
          else if (st.state === 'failed') setState((s) => ({ ...s, status: 'failed', error: st.error?.message ?? 'The live preview could not be made.' }));
          else if (st.state === 'cancelled') setState((s) => ({ ...s, status: 'off' }));
          else poll = window.setTimeout(() => void check(id), POLL_MS);
        } catch (err) {
          if (!stopped) setState((s) => ({ ...s, status: 'failed', error: readableError(err) }));
        }
      };
      void api.startLivePreview(assetId, sent).then(
        (st) => {
          if (stopped || !st.id) return;
          setState((s) => ({ ...s, status: 'working' }));
          void check(st.id);
        },
        (err: unknown) => {
          if (!stopped) setState((s) => ({ ...s, status: 'failed', error: readableError(err) }));
        },
      );
    }, DEBOUNCE_MS);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      if (poll !== undefined) window.clearTimeout(poll);
    };
  }, [assetId, enabled, key]);

  const sameAsset = state.asset === assetId;
  return {
    status: sameAsset && enabled ? state.status : 'off',
    preview: sameAsset && enabled ? state.preview : null,
    current: sameAsset && state.preview !== null && state.key === key,
    error: sameAsset ? state.error : null,
  };
}
