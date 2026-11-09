"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface PollingResult<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  updatedAt: Date | null;
  refresh: () => void;
}

/**
 * Calls `fetcher` now and every `intervalMs` (paused while the tab is hidden).
 * `fetcher` must be stable (useCallback) or the effect restarts. Set `enabled` false to idle.
 */
export function usePolling<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  intervalMs: number,
  enabled = true,
): PollingResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const controller = useRef<AbortController | null>(null);

  const run = useCallback(async () => {
    controller.current?.abort();
    const ctl = new AbortController();
    controller.current = ctl;
    try {
      const result = await fetcher(ctl.signal);
      if (ctl.signal.aborted) return;
      setData(result);
      setError(null);
      setUpdatedAt(new Date());
    } catch (e) {
      if (ctl.signal.aborted) return;
      setError(e instanceof Error ? e.message : "Erreur inconnue");
    } finally {
      if (!ctl.signal.aborted) setLoading(false);
    }
  }, [fetcher]);

  useEffect(() => {
    if (!enabled) return;
    setLoading(true);
    void run();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void run();
    }, intervalMs);
    return () => {
      clearInterval(timer);
      controller.current?.abort();
    };
  }, [run, intervalMs, enabled]);

  return { data, error, loading, updatedAt, refresh: () => void run() };
}
