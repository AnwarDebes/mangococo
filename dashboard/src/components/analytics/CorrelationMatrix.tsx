"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { getCorrelations } from "@/lib/api";
import { cn } from "@/lib/utils";

function getCorrColor(value: number, isDiagonal: boolean): string {
  if (isDiagonal) return "bg-gray-700";
  if (value >= 0.7) return "bg-green-700";
  if (value >= 0.4) return "bg-green-500/50";
  if (value >= 0.1) return "bg-green-500/20";
  if (value >= -0.1) return "bg-gray-700";
  if (value >= -0.4) return "bg-red-500/20";
  if (value >= -0.7) return "bg-red-500/50";
  return "bg-red-700";
}

function getCorrLabel(value: number): string {
  if (value >= 0.8) return "Strong positive";
  if (value >= 0.5) return "Moderate positive";
  if (value >= 0.2) return "Weak positive";
  if (value >= -0.2) return "No correlation";
  if (value >= -0.5) return "Weak negative";
  if (value >= -0.8) return "Moderate negative";
  return "Strong negative";
}

export default function CorrelationMatrix() {
  const [period, setPeriod] = useState("30d");
  const [tooltip, setTooltip] = useState<{ s1: string; s2: string; val: number; x: number; y: number } | null>(null);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["correlations", period],
    queryFn: () => getCorrelations(period),
    refetchInterval: 300000,
  });

  const insights = useMemo(() => {
    if (!data) return { highest: null, lowest: null, divergence: [] as string[] };
    const symbols = data.symbols;
    let highest = { pair: "", val: -2 };
    let lowest = { pair: "", val: 2 };
    const divergence: string[] = [];

    for (let i = 0; i < symbols.length; i++) {
      for (let j = i + 1; j < symbols.length; j++) {
        const val = data.matrix[symbols[i]]?.[symbols[j]] ?? 0;
        if (val > highest.val) highest = { pair: `${symbols[i].replace("USDT", "")} / ${symbols[j].replace("USDT", "")}`, val };
        if (val < lowest.val) lowest = { pair: `${symbols[i].replace("USDT", "")} / ${symbols[j].replace("USDT", "")}`, val };
        if (val < 0.3) divergence.push(`${symbols[i].replace("USDT", "")} / ${symbols[j].replace("USDT", "")}`);
      }
    }

    return { highest, lowest, divergence };
  }, [data]);

  if (isError) return (
    <div className="card text-center py-8">
      <p className="text-sm text-gray-400">Data temporarily unavailable</p>
      <button onClick={() => refetch()} className="mt-2 text-xs text-goblin-500 hover:underline">Retry</button>
    </div>
  );

  if (isLoading || !data) return <div className="card skeleton-shimmer h-64" />;

  const symbols = data.symbols;

  return (
    <div className="card relative">
      <div className="flex items-center justify-between mb-3">
        <h3 className="section-title">Cross-Asset Correlation</h3>
        <div className="flex gap-1">
          {["7d", "30d", "90d"].map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={cn(
                "px-2 py-0.5 text-[10px] rounded font-medium transition-colors",
                period === p ? "bg-goblin-500/20 text-goblin-400" : "text-gray-500 hover:text-white"
              )}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="text-xs mx-auto">
          <thead>
            <tr>
              <th className="p-1" />
              {symbols.map((s) => (
                <th key={s} className="p-1 text-gray-500 font-medium">{s.replace("USDT", "")}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {symbols.map((s1, i) => (
              <tr key={s1}>
                <td className="p-1 text-gray-500 font-medium text-right pr-2">{s1.replace("USDT", "")}</td>
                {symbols.map((s2, j) => {
                  const val = data.matrix[s1]?.[s2] ?? 0;
                  const isDiag = i === j;
                  return (
                    <td key={s2} className="p-0.5">
                      <div
                        className={cn(
                          "w-12 h-10 rounded flex items-center justify-center cursor-default text-[10px] font-mono text-white",
                          getCorrColor(val, isDiag)
                        )}
                        onMouseEnter={(e) => !isDiag && setTooltip({ s1: s1.replace("USDT", ""), s2: s2.replace("USDT", ""), val, x: e.clientX, y: e.clientY })}
                        onMouseLeave={() => setTooltip(null)}
                      >
                        {val.toFixed(2)}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Insights */}
      <div className="mt-3 space-y-1 text-xs">
        {insights.highest && (
          <p className="text-gray-400">
            <span className="text-green-400">Highest:</span> {insights.highest.pair} ({insights.highest.val.toFixed(2)})
          </p>
        )}
        {insights.lowest && (
          <p className="text-gray-400">
            <span className="text-blue-400">Most diverse:</span> {insights.lowest.pair} ({insights.lowest.val.toFixed(2)})
          </p>
        )}
        {insights.divergence.length > 0 && (
          <p className="text-gray-400">
            <span className="text-yellow-400">Low correlation:</span> {insights.divergence.slice(0, 3).join(", ")}
          </p>
        )}
      </div>

      {tooltip && (
        <div
          className="fixed z-50 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-xs pointer-events-none shadow-xl"
          style={{ left: tooltip.x + 10, top: tooltip.y - 40 }}
        >
          <p className="text-white">{tooltip.s1} / {tooltip.s2}: <span className="font-mono">{tooltip.val.toFixed(4)}</span></p>
          <p className="text-gray-500 text-[10px]">{getCorrLabel(tooltip.val)}</p>
        </div>
      )}
    </div>
  );
}
