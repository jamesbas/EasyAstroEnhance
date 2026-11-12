import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { StarMaskResult } from '../api/types';

export function useStarMask(assetId: string | null, onError: (err: unknown) => void) {
  const [on, setOn] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<StarMaskResult | null>(null);
  const current = useRef(assetId);
  current.current = assetId;

  useEffect(() => {
    setOn(false);
    setResult(null);
    setLoading(false);
  }, [assetId]);

  const toggle = useCallback(
    (next: boolean) => {
      setOn(next);
      if (!next || !assetId) return;
      setLoading(true);
      api.starMask(assetId).then(
        (res) => {
          if (current.current === assetId) setResult(res);
        },
        (err) => {
          setOn(false);
          onError(err);
        },
      ).finally(() => setLoading(false));
    },
    [assetId, onError],
  );

  return { on, loading, result, toggle, overlayUrl: on && result?.reliable ? result.overlay_url : null };
}
