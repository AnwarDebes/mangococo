"use client";

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { API_BASE } from "@/lib/api";

/**
 * Subscribes to the SSE stream and invalidates React Query caches
 * when real-time events arrive from the backend.
 */
export function useRealtimeUpdates() {
  const queryClient = useQueryClient();
  const esRef = useRef<EventSource | null>(null);
  const retryRef = useRef(0);

  useEffect(() => {
    let retryTimeout: ReturnType<typeof setTimeout>;

    function connect() {
      if (esRef.current) {
        esRef.current.close();
      }

      try {
        const es = new EventSource(`${API_BASE}/api/stream`);
        esRef.current = es;

        es.onopen = () => {
          retryRef.current = 0;
        };

        // Trade executed → invalidate portfolio, positions, trades
        es.addEventListener("trade_executed", () => {
          queryClient.invalidateQueries({ queryKey: ["portfolio"] });
          queryClient.invalidateQueries({ queryKey: ["positions"] });
          queryClient.invalidateQueries({ queryKey: ["trades"] });
        });

        // Position update → invalidate positions, portfolio
        es.addEventListener("position_update", () => {
          queryClient.invalidateQueries({ queryKey: ["portfolio"] });
          queryClient.invalidateQueries({ queryKey: ["positions"] });
        });

        // Price update → invalidate tickers
        es.addEventListener("price_update", () => {
          queryClient.invalidateQueries({ queryKey: ["all-tickers"] });
        });

        // Sentiment update → invalidate sentiment
        es.addEventListener("sentiment_update", () => {
          queryClient.invalidateQueries({ queryKey: ["sentiment"] });
        });

        // Signal update → invalidate signals
        es.addEventListener("signal_update", () => {
          queryClient.invalidateQueries({ queryKey: ["signals"] });
        });

        es.onerror = () => {
          es.close();
          if (retryRef.current < 15) {
            const delay = Math.min(1000 * Math.pow(2, retryRef.current), 30000);
            retryRef.current++;
            retryTimeout = setTimeout(connect, delay);
          }
        };
      } catch {
        if (retryRef.current < 15) {
          const delay = Math.min(1000 * Math.pow(2, retryRef.current), 30000);
          retryRef.current++;
          retryTimeout = setTimeout(connect, delay);
        }
      }
    }

    connect();

    return () => {
      clearTimeout(retryTimeout);
      esRef.current?.close();
    };
  }, [queryClient]);
}
