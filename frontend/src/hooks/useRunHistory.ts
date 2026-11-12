import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { Run, RunDetail } from '../api/types';

// Run history for one asset; refetched whenever the asset's newest run changes (or a re-run is added).
export function useRunHistory(assetId: string | null, latestRunId: string | null): Run[] {
  const [state, setState] = useState<{ assetId: string | null; runs: Run[] }>({ assetId: null, runs: [] });

  useEffect(() => {
    if (!assetId) return undefined;
    let cancelled = false;
    api.listRuns(assetId).then(
      (res) => {
        if (!cancelled) setState({ assetId, runs: res.runs });
      },
      () => undefined,
    );
    return () => {
      cancelled = true;
    };
  }, [assetId, latestRunId]);

  return state.assetId === assetId ? state.runs : [];
}

// Full run detail (has_fixed_mapping, applied diagnostics) for the run currently compared.
export function useRunDetail(runId: string | null): RunDetail | null {
  const [state, setState] = useState<RunDetail | null>(null);

  useEffect(() => {
    if (!runId) return undefined;
    let cancelled = false;
    api.getRun(runId).then(
      (res) => {
        if (!cancelled) setState(res);
      },
      () => undefined,
    );
    return () => {
      cancelled = true;
    };
  }, [runId]);

  return state && state.id === runId ? state : null;
}
