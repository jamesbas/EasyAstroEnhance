import { useCallback, useEffect, useRef, useState } from 'react';
import { api, readableError } from '../api/client';
import type { Asset, Job, Stack } from '../api/types';

const ACTIVE_ITEM = new Set(['queued', 'running']);

export function assetIsActive(a: Asset): boolean {
  return a.status === 'inspecting' || (a.latest_item !== null && ACTIVE_ITEM.has(a.latest_item.state));
}

export interface Workspace {
  assets: Asset[];
  activeJobs: Job[];
  activeStacks: Stack[];
  loaded: boolean;
  offline: string | null;
  refresh: () => Promise<void>;
  upsert: (assets: Asset[]) => void;
  remove: (id: string) => void;
}

// Polls /assets, active jobs and active stacks ~1 s while anything is inspecting/queued/running (5 s in hidden tabs); idle = no polling.
export function useWorkspace(): Workspace {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [activeJobs, setActiveJobs] = useState<Job[]>([]);
  const [activeStacks, setActiveStacks] = useState<Stack[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [offline, setOffline] = useState<string | null>(null);
  const inFlight = useRef(false);
  const generation = useRef(0);

  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    const gen = generation.current;
    try {
      const [a, j, s] = await Promise.all([api.listAssets(), api.listJobs(true), api.listStacks(true)]);
      if (gen === generation.current) {
        setAssets(a.assets);
        setActiveJobs(j.jobs);
        setActiveStacks(s.stacks);
        setOffline(null);
        setLoaded(true);
      }
    } catch (err) {
      setOffline(readableError(err));
      setLoaded(true);
    } finally {
      inFlight.current = false;
    }
  }, []);

  const upsert = useCallback((incoming: Asset[]) => {
    generation.current++;
    setAssets((prev) => {
      const byId = new Map(prev.map((a) => [a.id, a]));
      for (const a of incoming) byId.set(a.id, a);
      const seen = new Set(prev.map((a) => a.id));
      return [...prev.map((a) => byId.get(a.id) as Asset), ...incoming.filter((a) => !seen.has(a.id))];
    });
  }, []);

  const remove = useCallback((id: string) => {
    generation.current++;
    setAssets((prev) => prev.filter((a) => a.id !== id));
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const busy = assets.some(assetIsActive) || activeJobs.length > 0 || activeStacks.length > 0 || offline !== null;

  useEffect(() => {
    if (!busy) return undefined;
    let timer = 0;
    let stopped = false;
    const schedule = () => {
      timer = window.setTimeout(async () => {
        await refresh();
        if (!stopped) schedule();
      }, document.hidden ? 5000 : 1000);
    };
    const onVisibility = () => {
      window.clearTimeout(timer);
      schedule();
    };
    schedule();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [busy, refresh]);

  return { assets, activeJobs, activeStacks, loaded, offline, refresh, upsert, remove };
}
