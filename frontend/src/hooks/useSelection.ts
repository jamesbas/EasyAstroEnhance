import { useCallback, useEffect, useRef, useState } from 'react';
import type { Asset } from '../api/types';

// `selectedIds` is the batch scope; `primaryId` is the image shown in the viewer.
export function useSelection(assets: Asset[]) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [primaryId, setPrimaryId] = useState<string | null>(null);
  const anchor = useRef<string | null>(null);

  useEffect(() => {
    const ids = new Set(assets.map((a) => a.id));
    setSelectedIds((prev) => {
      const next = prev.filter((id) => ids.has(id));
      return next.length === prev.length ? prev : next;
    });
    setPrimaryId((prev) => {
      if (prev && ids.has(prev)) return prev;
      return assets.length > 0 ? assets[0].id : null;
    });
  }, [assets]);

  // First image ever added becomes selected so "Enhance selected" works immediately.
  useEffect(() => {
    if (assets.length > 0 && selectedIds.length === 0 && primaryId === assets[0].id && anchor.current === null) {
      setSelectedIds([assets[0].id]);
      anchor.current = assets[0].id;
    }
  }, [assets, selectedIds.length, primaryId]);

  const select = useCallback(
    (id: string, mods: { shift: boolean; toggle: boolean }) => {
      if (mods.shift && anchor.current) {
        const order = assets.map((a) => a.id);
        const a = order.indexOf(anchor.current);
        const b = order.indexOf(id);
        if (a >= 0 && b >= 0) {
          const [lo, hi] = a < b ? [a, b] : [b, a];
          setSelectedIds(order.slice(lo, hi + 1));
          setPrimaryId(id);
          return;
        }
      }
      if (mods.toggle) {
        setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
      } else {
        setSelectedIds([id]);
      }
      setPrimaryId(id);
      anchor.current = id;
    },
    [assets],
  );

  const toggle = useCallback((id: string) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
    anchor.current = id;
  }, []);

  const choose = useCallback((ids: string[], primary: string | null) => {
    setSelectedIds(ids);
    if (primary) {
      setPrimaryId(primary);
      anchor.current = primary;
    }
  }, []);

  return { selectedIds, primaryId, setPrimaryId, select, toggle, choose };
}
