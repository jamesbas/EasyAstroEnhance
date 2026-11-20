import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { ReferenceDataOverview } from '../api/types';

export interface ReferenceData {
  overview: ReferenceDataOverview | null;
  starsReady: boolean;
  objectsReady: boolean;
  download: (key: string) => Promise<void>;
  cancel: (key: string) => Promise<void>;
  remove: (key: string) => Promise<void>;
}

// Status of the optional star and object catalogs; polls about once a second only while a download is running.
export function useReferenceData(onError: (err: unknown) => void): ReferenceData {
  const [overview, setOverview] = useState<ReferenceDataOverview | null>(null);
  const alive = useRef(true);

  const load = useCallback(async () => {
    try {
      const o = await api.referenceData();
      if (alive.current) setOverview(o);
    } catch (err) {
      onError(err);
    }
  }, [onError]);

  useEffect(() => {
    alive.current = true;
    void load();
    return () => {
      alive.current = false;
    };
  }, [load]);

  const downloading = overview?.items.some((m) => m.state === 'downloading') ?? false;
  useEffect(() => {
    if (!downloading) return undefined;
    const t = window.setInterval(() => void load(), 1000);
    return () => window.clearInterval(t);
  }, [downloading, load]);

  const act = useCallback(
    async (fn: () => Promise<ReferenceDataOverview>) => {
      try {
        setOverview(await fn());
      } catch (err) {
        onError(err);
      }
    },
    [onError],
  );

  return {
    overview,
    starsReady: overview?.groups.stars.ready ?? false,
    objectsReady: overview?.groups.objects.ready ?? false,
    download: (key) => act(() => api.downloadReference(key)),
    cancel: (key) => act(() => api.cancelReference(key)),
    remove: (key) => act(() => api.deleteReference(key)),
  };
}
