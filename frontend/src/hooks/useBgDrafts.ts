import { useCallback, useState } from 'react';
import type { Asset } from '../api/types';
import type { BgDraft } from '../types/ui';

function initialDraft(asset: Asset): BgDraft {
  return {
    samples: (asset.background?.samples ?? []).map((rect) => ({ rect, excluded: false })),
    suggestions: [],
    suggestNote: null,
    check: null,
    checkKey: null,
  };
}

// Sky-sample drafts live per image and are never copied between images.
export function useBgDrafts() {
  const [drafts, setDrafts] = useState<Record<string, BgDraft>>({});

  const draftFor = useCallback((asset: Asset): BgDraft => drafts[asset.id] ?? initialDraft(asset), [drafts]);

  const patch = useCallback((asset: Asset, fn: (d: BgDraft) => BgDraft) => {
    setDrafts((prev) => ({ ...prev, [asset.id]: fn(prev[asset.id] ?? initialDraft(asset)) }));
  }, []);

  const drop = useCallback((assetId: string) => {
    setDrafts((prev) => {
      const { [assetId]: _removed, ...rest } = prev;
      return rest;
    });
  }, []);

  return { draftFor, patch, drop };
}
