"use client";

import { useQuery } from "@tanstack/react-query";
import { Zap } from "lucide-react";
import { getSignals } from "@/lib/api";
import { formatPrice, getTimeSince, cn } from "@/lib/utils";
import type { Signal } from "@/types";

export default function SignalFeed() {
  const { data: signals, isLoading } = useQuery({
    queryKey: ["signals"],
    queryFn: getSignals,
    refetchInterval: 3000,
  });

  if (isLoading) {
    return (
      <div className="card animate-pulse space-y-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-12 rounded bg-gray-700" />
        ))}
      </div>
    );
  }

  return (
    <div className="card p-0">
      <div className="flex items-center gap-2 border-b border-gray-800 px-5 py-3">
        <Zap size={16} className="text-mango-500" />
        <h3 className="font-semibold text-white">Live Signals</h3>
      </div>
      <div className="max-h-96 overflow-y-auto">
        {!signals || signals.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-gray-500">
            No active signals
          </p>
        ) : (
          signals.map((signal: Signal) => (
            <div
              key={signal.signal_id}
              className="flex items-center gap-3 border-b border-gray-800/50 px-5 py-3 hover:bg-gray-800/30 transition-colors"
            >
              <span
                className={cn(
                  "badge min-w-[44px] justify-center",
                  signal.action === "BUY"
                    ? "badge-buy"
                    : signal.action === "SELL"
                    ? "badge-sell"
                    : "badge-hold"
                )}
              >
                {signal.action}
              </span>
              <div className="flex-1">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-white">
                    {signal.symbol}
                  </span>
                  <span className="text-xs text-gray-500">
                    ${formatPrice(signal.price)}
                  </span>
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <div className="h-1.5 flex-1 rounded-full bg-gray-700">
                    <div
                      className={cn(
                        "h-1.5 rounded-full transition-all",
                        signal.confidence >= 0.7
                          ? "bg-green-500"
                          : signal.confidence >= 0.4
                          ? "bg-yellow-500"
                          : "bg-red-500"
                      )}
                      style={{
                        width: `${signal.confidence * 100}%`,
                      }}
                    />
                  </div>
                  <span className="text-xs text-gray-400">
                    {(signal.confidence * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
              <span className="text-xs text-gray-500 whitespace-nowrap">
                {getTimeSince(signal.timestamp)}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
