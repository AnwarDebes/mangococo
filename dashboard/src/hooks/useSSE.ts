"use client";

import { useState, useEffect, useRef, useCallback } from "react";

interface UseSSEResult<T> {
  data: T | null;
  isConnected: boolean;
  error: string | null;
}

export function useSSE<T = unknown>(url: string): UseSSEResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const retryCount = useRef(0);
  const maxRetries = 10;
  const eventSourceRef = useRef<EventSource | null>(null);

  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onopen = () => {
      setIsConnected(true);
      setError(null);
      retryCount.current = 0;
    };

    es.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data) as T;
        setData(parsed);
      } catch {
        setData(event.data as unknown as T);
      }
    };

    es.onerror = () => {
      es.close();
      setIsConnected(false);

      if (retryCount.current < maxRetries) {
        const delay = Math.min(
          1000 * Math.pow(2, retryCount.current),
          30000
        );
        retryCount.current += 1;
        setError(`Disconnected. Reconnecting in ${delay / 1000}s...`);
        setTimeout(connect, delay);
      } else {
        setError("Connection lost. Please refresh the page.");
      }
    };
  }, [url]);

  useEffect(() => {
    connect();
    return () => {
      eventSourceRef.current?.close();
    };
  }, [connect]);

  return { data, isConnected, error };
}
