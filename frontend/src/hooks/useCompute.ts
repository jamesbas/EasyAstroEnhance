import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import type { ComputeInfo } from '../api/types';

export function useCompute(): { compute: ComputeInfo | null; setCompute: (c: ComputeInfo) => void; reload: () => void } {
  const [compute, setCompute] = useState<ComputeInfo | null>(null);
  const reload = useCallback(() => {
    api.getCompute().then(setCompute, () => undefined);
  }, []);
  useEffect(reload, [reload]);
  return { compute, setCompute, reload };
}
