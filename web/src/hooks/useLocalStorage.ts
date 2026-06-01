'use client';
import { useState, useCallback, useEffect } from 'react';

/**
 * #30 — Persist state across page reloads via localStorage.
 * Uses a two-pass render to avoid SSR/client hydration mismatch:
 * first render always uses initialValue (matches server), then
 * after mount reads localStorage and updates if a saved value exists.
 */
export function useLocalStorage<T>(key: string, initialValue: T): [T, (value: T | ((prev: T) => T)) => void] {
  const [stored, setStored] = useState<T>(initialValue);

  // Read from localStorage only after mount so server and first client render match
  useEffect(() => {
    try {
      const item = window.localStorage.getItem(key);
      if (item !== null) setStored(JSON.parse(item) as T);
    } catch {
      // ignore parse / access errors
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const setValue = useCallback((value: T | ((prev: T) => T)) => {
    setStored((prev) => {
      const next = typeof value === 'function' ? (value as (p: T) => T)(prev) : value;
      try {
        window.localStorage.setItem(key, JSON.stringify(next));
      } catch {
        // Ignore write errors (quota, private mode)
      }
      return next;
    });
  }, [key]);

  return [stored, setValue];
}
