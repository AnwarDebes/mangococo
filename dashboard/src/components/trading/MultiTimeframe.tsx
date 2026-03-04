"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { getMultiTimeframe } from "@/lib/api";
import { cn } from "@/lib/utils";

const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"];
const TIMEFRAMES = ["5m", "15m", "1h", "4h"] as const;

interface MiniChartProps {
  label: string;
  candles: Array<{ time: number; open: number; high: number; low: number; close: number; volume: number }>;
}

function MiniCandlestick({ label, candles }: MiniChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof import("lightweight-charts").createChart> | null>(null);

  useEffect(() => {
    if (!containerRef.current || candles.length === 0) return;

    let disposed = false;

    import("lightweight-charts").then((lw) => {
      if (disposed || !containerRef.current) return;

      // Clean up previous chart
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }

      const chart = lw.createChart(containerRef.current, {
        width: containerRef.current.clientWidth,
        height: containerRef.current.clientHeight,
        layout: {
          background: { color: "transparent" } as { color: string },
          textColor: "#6b7280",
          fontSize: 9,
        },
        grid: {
          vertLines: { color: "rgba(55, 65, 81, 0.3)" },
          horzLines: { color: "rgba(55, 65, 81, 0.3)" },
        },
        rightPriceScale: { borderColor: "#1f2937" },
        timeScale: { borderColor: "#1f2937", timeVisible: true },
        crosshair: { mode: 0 },
      });

      const series = chart.addCandlestickSeries({
        upColor: "#22c55e",
        downColor: "#ef4444",
        borderDownColor: "#ef4444",
        borderUpColor: "#22c55e",
        wickDownColor: "#ef4444",
        wickUpColor: "#22c55e",
      });

      series.setData(candles as unknown as Parameters<typeof series.setData>[0]);
      chart.timeScale().fitContent();
      chartRef.current = chart;

      const resizeObserver = new ResizeObserver((entries) => {
        if (entries[0] && chartRef.current) {
          const { width, height } = entries[0].contentRect;
          chartRef.current.applyOptions({ width, height });
        }
      });
      resizeObserver.observe(containerRef.current);

      return () => {
        resizeObserver.disconnect();
      };
    });

    return () => {
      disposed = true;
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [candles]);

  return (
    <div className="rounded-lg bg-gray-950/50 border border-gray-800/50 p-2 relative">
      <span className="absolute top-2 left-2 z-10 text-[10px] font-bold text-goblin-400 bg-gray-900/80 px-1.5 py-0.5 rounded">
        {label}
      </span>
      <div ref={containerRef} className="w-full h-full min-h-[160px]" />
    </div>
  );
}

export default function MultiTimeframe() {
  const [symbol, setSymbol] = useState("BTCUSDT");

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["multi-timeframe", symbol],
    queryFn: () => getMultiTimeframe(symbol),
    refetchInterval: 30000,
  });

  if (isError) return (
    <div className="card text-center py-8">
      <p className="text-sm text-gray-400">Data temporarily unavailable</p>
      <button onClick={() => refetch()} className="mt-2 text-xs text-goblin-500 hover:underline">Retry</button>
    </div>
  );

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="section-title">Multi-Timeframe</h3>
        <div className="flex gap-1">
          {SYMBOLS.map((s) => (
            <button
              key={s}
              onClick={() => setSymbol(s)}
              className={cn(
                "px-2 py-0.5 text-[10px] rounded font-medium transition-colors",
                symbol === s ? "bg-goblin-500/20 text-goblin-400" : "text-gray-500 hover:text-white"
              )}
            >
              {s.replace("USDT", "")}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-2 gap-2">
          {TIMEFRAMES.map((tf) => (
            <div key={tf} className="skeleton-shimmer h-[180px] rounded-lg" />
          ))}
        </div>
      ) : data ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {TIMEFRAMES.map((tf) => (
            <MiniCandlestick
              key={`${symbol}-${tf}`}
              label={tf}
              candles={data[tf] || []}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
