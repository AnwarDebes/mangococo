"use client";

import { useQuery } from "@tanstack/react-query";
import { getDerivativesFunding } from "@/lib/api";
import { cn } from "@/lib/utils";

function interpret(rate: number, ratio: number, oiChange: number): string {
  if (rate > 0.05 && ratio > 1.3) return "Heavy long positioning - liquidation risk elevated";
  if (rate < -0.01 && ratio < 0.8) return "Short squeeze potential - shorts paying premium";
  if (Math.abs(rate) < 0.01 && Math.abs(oiChange) < 3) return "Neutral positioning - no clear leverage bias";
  if (oiChange > 10) return "Rapid leverage build-up - watch for volatility";
  return "Moderate positioning";
}

export default function MarketPositioning() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["derivatives-funding"],
    queryFn: getDerivativesFunding,
    refetchInterval: 60000,
  });

  if (isError) return (
    <div className="card text-center py-8">
      <p className="text-sm text-gray-400">Data temporarily unavailable</p>
      <button onClick={() => refetch()} className="mt-2 text-xs text-goblin-500 hover:underline">Retry</button>
    </div>
  );

  if (isLoading || !data) return <div className="card skeleton-shimmer h-48" />;

  return (
    <div className="card">
      <h3 className="section-title mb-3">Market Positioning</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {data.symbols.map((sym) => {
          const rate = sym.current_rate * 100;
          const longPct = 50 + rate * 100;
          const shortPct = 100 - longPct;
          const interp = interpret(rate, 1 + rate * 10, 0);

          return (
            <div key={sym.symbol} className="p-3 rounded-xl bg-gray-900/50 border border-gray-800/50 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-bold text-white">{sym.symbol.replace("USDT", "")}</span>
                <span className={cn(
                  "text-xs font-mono",
                  rate > 0.03 ? "text-red-400" : rate < -0.01 ? "text-green-400" : "text-gray-400"
                )}>
                  {rate >= 0 ? "+" : ""}{rate.toFixed(4)}%
                </span>
              </div>

              {/* Long/Short bar */}
              <div className="flex h-2 rounded-full overflow-hidden">
                <div className="bg-green-500/70" style={{ width: `${Math.max(5, Math.min(95, longPct))}%` }} />
                <div className="bg-red-500/70" style={{ width: `${Math.max(5, Math.min(95, shortPct))}%` }} />
              </div>
              <div className="flex justify-between text-[9px]">
                <span className="text-green-400">{Math.max(0, longPct).toFixed(0)}% Long</span>
                <span className="text-red-400">{Math.max(0, shortPct).toFixed(0)}% Short</span>
              </div>

              <p className="text-[10px] text-gray-500 leading-tight">{interp}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
