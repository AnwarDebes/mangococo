"use client";

import { useQuery } from "@tanstack/react-query";
import { getDerivativesFunding } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AlertTriangle } from "lucide-react";
import { useState } from "react";

function getRateColor(rate: number): string {
  if (rate <= -0.02) return "bg-green-700";
  if (rate < -0.005) return "bg-green-500/60";
  if (rate < 0.005) return "bg-gray-600";
  if (rate < 0.02) return "bg-red-500/40";
  if (rate < 0.05) return "bg-red-500/70";
  return "bg-red-700";
}

export default function FundingHeatmap() {
  const [tooltip, setTooltip] = useState<{ symbol: string; rate: number; x: number; y: number } | null>(null);

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

  const columns = ["Current", "8h ago", "16h ago", "24h ago", "2d ago", "3d ago"];

  return (
    <div className="card">
      <h3 className="section-title mb-3">Funding Rate Heatmap</h3>
      <div className="overflow-x-auto relative">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500">
              <th className="pb-2 text-left font-medium pr-3">Symbol</th>
              {columns.map((col) => (
                <th key={col} className="pb-2 font-medium text-center px-1">{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.symbols.map((sym) => {
              const rates = [sym.current_rate, ...sym.history.map((h) => h.rate)];
              return (
                <tr key={sym.symbol} className="border-t border-gray-800/50">
                  <td className="py-1.5 pr-3 font-medium text-white">{sym.symbol.replace("USDT", "")}</td>
                  {columns.map((_, idx) => {
                    const rate = rates[idx] ?? 0;
                    const pct = (rate * 100).toFixed(4);
                    return (
                      <td key={idx} className="py-1.5 px-1 text-center">
                        <div
                          className={cn("rounded px-1.5 py-0.5 inline-flex items-center gap-0.5 cursor-default", getRateColor(rate * 100))}
                          onMouseEnter={(e) => setTooltip({ symbol: sym.symbol, rate: rate * 100, x: e.clientX, y: e.clientY })}
                          onMouseLeave={() => setTooltip(null)}
                        >
                          <span className="text-white font-mono text-[10px]">{pct}%</span>
                          {rate * 100 > 0.05 && <AlertTriangle size={10} className="text-yellow-400" />}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>

        {tooltip && (
          <div
            className="fixed z-50 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-xs pointer-events-none shadow-xl"
            style={{ left: tooltip.x + 10, top: tooltip.y - 60 }}
          >
            <p className="text-white font-medium">{tooltip.symbol}</p>
            <p className="text-gray-400">Rate: {tooltip.rate.toFixed(4)}%</p>
            <p className="text-gray-400">Annualized: {(tooltip.rate * 3 * 365).toFixed(1)}%</p>
            <p className="text-gray-500 text-[10px] mt-0.5">
              {tooltip.rate > 0.05 ? "Heavy long leverage - liquidation risk" :
               tooltip.rate < -0.02 ? "Shorts paying premium - squeeze potential" :
               "Normal range"}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
