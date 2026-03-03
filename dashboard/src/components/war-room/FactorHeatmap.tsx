"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getPredictionFactors } from "@/lib/api";
import { cn } from "@/lib/utils";

const FACTORS = ["RSI", "MACD", "Volume", "Sentiment", "Whale", "Trend", "Volatility", "Momentum"];

function getHeatColor(direction: string, value: number): string {
  if (direction === "bullish") return "bg-green-500";
  if (direction === "bearish") return "bg-red-500";
  return "bg-gray-600";
}

function getHeatOpacity(direction: string): string {
  if (direction === "neutral") return "opacity-30";
  return "opacity-70";
}

export default function FactorHeatmap() {
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);

  const { data: rows = [] } = useQuery({
    queryKey: ["prediction-factors"],
    queryFn: getPredictionFactors,
    refetchInterval: 15000,
  });

  return (
    <div className="flex h-full flex-col relative">
      <p className="text-xs text-gray-500 mb-2 font-medium">Factor Heatmap</p>
      <div className="overflow-x-auto flex-1 min-h-0">
        <table className="w-full text-[10px]">
          <thead>
            <tr>
              <th className="text-left text-gray-500 pb-1.5 pr-2 font-medium">Symbol</th>
              {FACTORS.map((f) => (
                <th key={f} className="text-center text-gray-500 pb-1.5 px-0.5 font-medium whitespace-nowrap">
                  {f.slice(0, 4)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.symbol}>
                <td className="text-white font-medium py-1 pr-2 whitespace-nowrap">
                  {row.symbol.replace("/USDT", "")}
                </td>
                {FACTORS.map((factor) => {
                  const cell = row.factors[factor];
                  if (!cell) {
                    return (
                      <td key={factor} className="px-0.5 py-1">
                        <div className="h-5 w-full rounded bg-gray-800" />
                      </td>
                    );
                  }
                  return (
                    <td key={factor} className="px-0.5 py-1">
                      <div
                        className={cn(
                          "h-5 w-full rounded cursor-pointer transition-all hover:scale-110",
                          getHeatColor(cell.direction, cell.value),
                          getHeatOpacity(cell.direction)
                        )}
                        onMouseEnter={(e) => {
                          const rect = e.currentTarget.getBoundingClientRect();
                          setTooltip({
                            x: rect.left + rect.width / 2,
                            y: rect.top - 8,
                            text: cell.description || `${factor}: ${cell.value}`,
                          });
                        }}
                        onMouseLeave={() => setTooltip(null)}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={FACTORS.length + 1} className="text-center text-gray-600 py-4">
                  Loading factors...
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-3 mt-2 text-[9px] text-gray-500">
        <div className="flex items-center gap-1">
          <div className="h-2.5 w-2.5 rounded bg-green-500 opacity-70" />
          Bullish
        </div>
        <div className="flex items-center gap-1">
          <div className="h-2.5 w-2.5 rounded bg-red-500 opacity-70" />
          Bearish
        </div>
        <div className="flex items-center gap-1">
          <div className="h-2.5 w-2.5 rounded bg-gray-600 opacity-30" />
          Neutral
        </div>
      </div>

      {/* Tooltip (rendered via portal-like fixed positioning) */}
      {tooltip && (
        <div
          className="fixed z-50 pointer-events-none bg-gray-900 border border-gray-700 rounded px-2 py-1 text-[10px] text-white whitespace-nowrap -translate-x-1/2 -translate-y-full"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          {tooltip.text}
        </div>
      )}
    </div>
  );
}
