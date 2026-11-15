import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { AIOverview } from '../api/types';

export interface AIModels {
  overview: AIOverview | null;
  download: (key: string) => Promise<void>;
  cancel: (key: string) => Promise<void>;
  remove: (key: string) => Promise<void>;
}

// Model status for the optional AI tools; polls about once a second only while a download is running.
export function useAIModels(onError: (err: unknown) => void): AIModels {
  const [overview, setOverview] = useState<AIOverview | null>(null);
  const alive = useRef(true);

  const load = useCallback(async () => {
    try {
      const o = await api.aiModels();
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

  const downloading = overview?.models.some((m) => m.state === 'downloading') ?? false;
  useEffect(() => {
    if (!downloading) return undefined;
    const t = window.setInterval(() => void load(), 1000);
    return () => window.clearInterval(t);
  }, [downloading, load]);

  const act = useCallback(
    async (fn: () => Promise<AIOverview>) => {
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
    download: (key) => act(() => api.downloadAI(key)),
    cancel: (key) => act(() => api.cancelAI(key)),
    remove: (key) => act(() => api.deleteAI(key)),
  };
}
