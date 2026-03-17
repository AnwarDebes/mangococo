"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getCandles, getTicker } from "@/lib/api";
import { cn } from "@/lib/utils";

const SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"] as const;
const INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1D"] as const;

export default function PriceChart() {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof import("lightweight-charts").createChart> | null>(null);
  const [activeSymbol, setActiveSymbol] = useState<string>("BTC/USDT");
  const [activeInterval, setActiveInterval] = useState<string>("1h");
  const [isLoaded, setIsLoaded] = useState(false);
  const [currentPrice, setCurrentPrice] = useState<number | null>(null);

  // Fetch candles
  const { data: candles = [], isError: candleError } = useQuery({
    queryKey: ["candles", activeSymbol, activeInterval],
    queryFn: () => getCandles(activeSymbol, activeInterval, 200),
    refetchInterval: 30000,
  });

  // Fetch current ticker price
  const { data: tickerData } = useQuery({
    queryKey: ["ticker", activeSymbol],
    queryFn: () => getTicker(activeSymbol),
    refetchInterval: 5000,
  });

  useEffect(() => {
    if (tickerData && typeof tickerData === "object") {
      const t = tickerData as Record<string, string>;
      const price = parseFloat(t.lastPrice || t.price || "0");
      if (price > 0) setCurrentPrice(price);
    }
  }, [tickerData]);

  useEffect(() => {
    let mounted = true;

    async function initChart() {
      if (!chartContainerRef.current || candles.length === 0) return;

      const { createChart, ColorType, CrosshairMode } = await import("lightweight-charts");

      if (!mounted || !chartContainerRef.current) return;

      if (chartRef.current) {
        chartRef.current.remove();
      }

      const chart = createChart(chartContainerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: "#030712" },
          textColor: "#6b7280",
        },
        grid: {
          vertLines: { color: "rgba(34,197,94,0.04)" },
          horzLines: { color: "rgba(34,197,94,0.04)" },
        },
        crosshair: { mode: CrosshairMode.Normal },
        rightPriceScale: { borderColor: "rgba(107,114,128,0.2)" },
        timeScale: { borderColor: "rgba(107,114,128,0.2)", timeVisible: true },
        width: chartContainerRef.current.clientWidth,
        height: 400,
      });

      chartRef.current = chart;

      const candleSeries = chart.addCandlestickSeries({
        upColor: "#22c55e",
        downColor: "#ef4444",
        borderDownColor: "#ef4444",
        borderUpColor: "#22c55e",
        wickDownColor: "#ef4444",
        wickUpColor: "#22c55e",
      });

      const volumeSeries = chart.addHistogramSeries({
        color: "#22c55e",
        priceFormat: { type: "volume" },
        priceScaleId: "",
      });

      chart.priceScale("").applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });

      candleSeries.setData(
        candles.map((c) => ({
          time: c.time as import("lightweight-charts").Time,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        }))
      );

      volumeSeries.setData(
        candles.map((c) => ({
          time: c.time as import("lightweight-charts").Time,
          value: c.volume,
          color: c.close >= c.open ? "rgba(34,197,94,0.3)" : "rgba(239,68,68,0.3)",
        }))
      );

      chart.timeScale().fitContent();

      const observer = new ResizeObserver((entries) => {
        if (entries[0] && chartRef.current) {
          chartRef.current.applyOptions({ width: entries[0].contentRect.width });
        }
      });

      observer.observe(chartContainerRef.current);
      setIsLoaded(true);

      return () => {
        observer.disconnect();
        if (chartRef.current) {
          chartRef.current.remove();
          chartRef.current = null;
        }
      };
    }

    initChart();

    return () => {
      mounted = false;
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [candles, activeInterval, activeSymbol]);

  return (
    <div className="card">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-3">
          <h3 className="section-title text-base">{activeSymbol} Price Chart</h3>
          {currentPrice !== null && (
            <span className="font-mono text-sm text-white">
              ${currentPrice < 1 ? currentPrice.toFixed(4) : currentPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })}
            </span>
          )}
        </div>
        <div className="flex gap-1 flex-wrap">
          {INTERVALS.map((interval) => (
            <button
              key={interval}
              onClick={() => setActiveInterval(interval)}
              className={cn(
                "rounded px-2 py-1 text-xs font-medium transition-all",
                activeInterval === interval
                  ? "bg-goblin-500/20 text-goblin-400 border border-goblin-500/30"
                  : "text-gray-500 hover:text-gray-300 border border-transparent"
              )}
            >
              {interval}
            </button>
          ))}
        </div>
      </div>

      {/* Symbol selector */}
      <div className="flex gap-1 mb-3 flex-wrap">
        {SYMBOLS.map((sym) => (
          <button
            key={sym}
            onClick={() => setActiveSymbol(sym)}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium transition-all",
              activeSymbol === sym
                ? "bg-goblin-500/20 text-goblin-400 ring-1 ring-goblin-500/30"
                : "bg-gray-800/50 text-gray-500 hover:text-gray-300"
            )}
          >
            {sym.replace("/USDT", "")}
          </button>
        ))}
      </div>

      <div
        ref={chartContainerRef}
        className="rounded-lg border border-goblin-500/10 bg-gray-950 overflow-hidden"
        style={{ height: 400 }}
      >
        {!isLoaded && (
          <div className="flex h-full items-center justify-center">
            <div className="text-sm text-gray-500">
              {candleError
                ? "Failed to load chart data. Retrying..."
                : candles.length === 0
                ? "Loading chart data..."
                : "Rendering chart..."}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
