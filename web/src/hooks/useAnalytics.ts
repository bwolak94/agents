'use client';
import { useState, useEffect, useCallback } from 'react';
import type { AnalyticsSummary } from '@/types/analytics';
import { API_URL } from '@/constants/api';

interface UseAnalyticsResult {
  data: AnalyticsSummary | null;
  loading: boolean;
  refetch: () => void;
}

export function useAnalytics(): UseAnalyticsResult {
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);

  const refetch = useCallback(() => {
    setTick((t) => t + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    fetch(`${API_URL}/analytics`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<AnalyticsSummary>;
      })
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [tick]);

  return { data, loading, refetch };
}
