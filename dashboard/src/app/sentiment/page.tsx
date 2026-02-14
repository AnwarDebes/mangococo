"use client";

import { useQuery } from "@tanstack/react-query";
import { getSentiment } from "@/lib/api";
import { cn } from "@/lib/utils";
import SentimentGauge from "@/components/charts/SentimentGauge";
import type { SentimentData } from "@/types";

export default function SentimentPage() {
  const { data: sentiments, isLoading } = useQuery({
    queryKey: ["sentiment"],
    queryFn: getSentiment,
    refetchInterval: 30000,
  });

  // Average fear & greed from all symbols
  const avgFearGreed =
    sentiments && sentiments.length > 0
      ? Math.round(
          sentiments.reduce((s: number, d: SentimentData) => s + d.fear_greed_index, 0) /
            sentiments.length
        )
      : 50;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Market Sentiment</h1>
        <p className="text-sm text-gray-400">
          Fear & Greed index and per-symbol analysis
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Fear & Greed Gauge */}
        <div className="card lg:col-span-1">
          <h3 className="mb-4 text-center font-semibold text-white">
            Fear & Greed Index
          </h3>
          <SentimentGauge value={avgFearGreed} />
        </div>

        {/* Per-symbol sentiment */}
        <div className="card lg:col-span-2">
          <h3 className="mb-4 font-semibold text-white">Symbol Sentiment</h3>
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-10 animate-pulse rounded bg-gray-700" />
              ))}
            </div>
          ) : !sentiments || sentiments.length === 0 ? (
            <p className="text-sm text-gray-500">No sentiment data available</p>
          ) : (
            <div className="space-y-4">
              {sentiments.map((s: SentimentData) => (
                <div key={s.symbol}>
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-medium text-white">{s.symbol}</span>
                    <div className="flex items-center gap-4 text-xs text-gray-400">
                      <span>1h: <span className={cn(s.momentum_1h >= 0 ? "text-profit" : "text-loss")}>{s.momentum_1h >= 0 ? "+" : ""}{s.momentum_1h.toFixed(2)}</span></span>
                      <span>24h: <span className={cn(s.momentum_24h >= 0 ? "text-profit" : "text-loss")}>{s.momentum_24h >= 0 ? "+" : ""}{s.momentum_24h.toFixed(2)}</span></span>
                      <span className="font-mono">{s.score.toFixed(1)}</span>
                    </div>
                  </div>
                  <div className="mt-1 h-2 rounded-full bg-gray-700">
                    <div
                      className={cn(
                        "h-2 rounded-full transition-all",
                        s.score >= 60
                          ? "bg-green-500"
                          : s.score >= 40
                          ? "bg-yellow-500"
                          : "bg-red-500"
                      )}
                      style={{ width: `${Math.max(2, s.score)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* News / Sentiment Stream placeholder */}
      <div className="card">
        <h3 className="mb-4 font-semibold text-white">Recent News Sentiment</h3>
        <div className="space-y-3">
          {isLoading ? (
            Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-16 animate-pulse rounded bg-gray-700" />
            ))
          ) : (
            <div className="flex flex-col items-center py-8 text-gray-500">
              <p className="text-sm">News sentiment feed will appear here</p>
              <p className="mt-1 text-xs text-gray-600">
                Connect a news API to populate this section
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
