import { useEffect, useState } from 'react';
import { api } from '../api/client';

export interface AppVersion {
  version: string;
  recipeSchema: number;
  stackVersion: string;
}

// The version reported by the running backend (the processing engine actually used for new results).
export function useAppVersion(): AppVersion | null {
  const [info, setInfo] = useState<AppVersion | null>(null);
  useEffect(() => {
    let cancelled = false;
    api.session().then(
      (s) => {
        if (!cancelled) setInfo({ version: s.version, recipeSchema: s.recipe_schema, stackVersion: s.stack_version });
      },
      () => undefined,
    );
    return () => {
      cancelled = true;
    };
  }, []);
  return info;
}
