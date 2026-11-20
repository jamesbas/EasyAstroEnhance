import { useCallback, useState } from 'react';

// A small UI preference kept in localStorage (never settings that change processing).
export function usePersistent<T extends string>(key: string, fallback: T, allowed: readonly T[]): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const v = window.localStorage.getItem(key) as T | null;
      return v !== null && allowed.includes(v) ? v : fallback;
    } catch {
      return fallback;
    }
  });
  const set = useCallback((v: T) => {
    setValue(v);
    try {
      window.localStorage.setItem(key, v);
    } catch {
      // storage unavailable (private mode): keep the choice for this session only
    }
  }, [key]);
  return [value, set];
}
