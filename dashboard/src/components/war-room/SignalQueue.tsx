"use client";

import { useQuery } from "@tanstack/react-query";
import { getSignals } from "@/lib/api";
import { cn } from "@/lib/utils";
import { getTimeSince } from "@/lib/utils";

export default function SignalQueue() {
  const { data: signals = [] } = useQuery({
    queryKey: ["signals-queue"],
    queryFn: getSignals,
    refetchInterval: 5000,
  });

  const recent = signals.slice(0, 15);

  return (
    <div className="flex h-full flex-col">
      <p className="text-xs text-gray-500 mb-2 font-medium">Signal Queue</p>
      <div className="flex-1 overflow-y-auto space-y-1.5 min-h-0">
        {recent.length === 0 ? (
          <div className="flex h-full items-center justify-center text-xs text-gray-600">
            Waiting for signals...
          </div>
        ) : (
          recent.map((s, i) => {
            const borderColor =
              s.action === "BUY"
                ? "border-l-green-500"
                : s.action === "SELL"
                ? "border-l-red-500"
                : "border-l-gray-500";
            const badgeBg =
              s.action === "BUY"
                ? "bg-green-500/20 text-green-400"
                : s.action === "SELL"
                ? "bg-red-500/20 text-red-400"
                : "bg-gray-500/20 text-gray-400";

            return (
              <div
                key={s.signal_id}
                className={cn(
                  "border-l-2 rounded-r-lg bg-gray-800/40 px-2.5 py-2 transition-all",
                  "animate-fade-in",
                  borderColor
                )}
                style={{ animationDelay: `${i * 30}ms` }}
              >
                <div className="flex items-center justify-between gap-1">
                  <span className="text-xs font-bold text-white truncate">
                    {s.symbol.replace("USDT", "")}
                  </span>
                  <span className={cn("text-[9px] font-bold px-1.5 py-0.5 rounded", badgeBg)}>
                    {s.action}
                  </span>
                </div>
                <div className="mt-1 flex items-center gap-2">
                  {/* Confidence bar */}
                  <div className="h-1 flex-1 rounded-full bg-gray-700">
                    <div
                      className={cn(
                        "h-1 rounded-full transition-all",
                        s.confidence > 0.7
                          ? "bg-goblin-500"
                          : s.confidence > 0.5
                          ? "bg-yellow-500"
                          : "bg-gray-500"
                      )}
                      style={{ width: `${Math.min(s.confidence * 100, 100)}%` }}
                    />
                  </div>
                  <span className="text-[9px] text-gray-500 whitespace-nowrap">
                    {getTimeSince(s.timestamp)}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
