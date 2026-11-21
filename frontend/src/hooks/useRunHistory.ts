import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { Run, RunDetail } from '../api/types';

// Run history for one asset; refetched whenever the asset's current run changes, a re-run is added or ``version`` changes
// (for example after a result was deleted).
export function useRunHistory(assetId: string | null, latestRunId: string | null, version = 0): Run[] {
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
  }, [assetId, latestRunId, version]);

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
