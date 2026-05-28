'use client';
import { useState, useCallback } from 'react';

/**
 * #30 — Persist state across page reloads via localStorage.
 * Falls back gracefully if localStorage is unavailable (SSR / private mode).
 */
export function useLocalStorage<T>(key: string, initialValue: T): [T, (value: T | ((prev: T) => T)) => void] {
  const [stored, setStored] = useState<T>(() => {
    if (typeof window === 'undefined') return initialValue;
    try {
      const item = window.localStorage.getItem(key);
      return item !== null ? (JSON.parse(item) as T) : initialValue;
    } catch {
      return initialValue;
    }
  });

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
