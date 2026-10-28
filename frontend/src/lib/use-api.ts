"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "./api";

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const current = useRef(path);
  current.current = path;

  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      const result = await api.get<T>(path);
      if (current.current === path) {
        setData(result);
        setError(null);
      }
    } catch (e) {
      if (current.current === path) setError(errorMessage(e));
    } finally {
      if (current.current === path) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload, setData };
}
