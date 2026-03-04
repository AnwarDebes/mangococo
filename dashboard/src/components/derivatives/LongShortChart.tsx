"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ComposedChart,
  Bar,
  Line,
  ResponsiveContainer,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
} from "recharts";
import { getLongShort } from "@/lib/api";
import { cn } from "@/lib/utils";

const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"];

export default function LongShortChart() {
  const [symbol, setSymbol] = useState("BTCUSDT");

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["long-short", symbol],
    queryFn: () => getLongShort(symbol),
    refetchInterval: 60000,
  });

  const chartData = useMemo(() => {
    if (!data) return [];
    const ratios = data.long_short_ratio || [];
    const takers = data.taker_volume || [];
    const len = Math.min(ratios.length, takers.length);
    const result = [];
    for (let i = 0; i < len; i++) {
      result.push({
        time: new Date(ratios[i].timestamp).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
        ratio: parseFloat(ratios[i].longShortRatio),
        buyVol: parseFloat(takers[i]?.buyVol || "0") / 1e6,
        sellVol: -parseFloat(takers[i]?.sellVol || "0") / 1e6,
      });
    }
    return result;
  }, [data]);

  const currentRatio = chartData.length > 0 ? chartData[chartData.length - 1].ratio : 1;
  const isExtremeLong = currentRatio > 1.5;
  const isExtremeShort = currentRatio < 0.7;

  if (isError) return (
    <div className="card text-center py-8">
      <p className="text-sm text-gray-400">Data temporarily unavailable</p>
      <button onClick={() => refetch()} className="mt-2 text-xs text-goblin-500 hover:underline">Retry</button>
    </div>
  );

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="section-title">Long/Short Ratio</h3>
        {isExtremeLong && <span className="badge bg-red-500/20 text-red-400 text-[9px]">Extremely Long</span>}
        {isExtremeShort && <span className="badge bg-green-500/20 text-green-400 text-[9px]">Extremely Short</span>}
      </div>

      <div className="flex gap-1 mb-3 overflow-x-auto">
        {SYMBOLS.map((s) => (
          <button
            key={s}
            onClick={() => setSymbol(s)}
            className={cn(
              "px-2 py-1 text-[10px] rounded-md font-medium transition-colors whitespace-nowrap",
              symbol === s ? "bg-goblin-500/20 text-goblin-400" : "text-gray-500 hover:text-white"
            )}
          >
            {s.replace("USDT", "")}
          </button>
        ))}
      </div>

      <p className="text-lg font-bold text-white mb-2">
        {currentRatio.toFixed(2)}
        <span className="text-xs text-gray-500 font-normal ml-2">L/S Ratio</span>
      </p>

      {isLoading ? (
        <div className="h-[180px] skeleton-shimmer rounded-lg" />
      ) : (
        <div className="h-[180px]">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData}>
              <XAxis dataKey="time" hide />
              <YAxis yAxisId="vol" hide />
              <YAxis yAxisId="ratio" hide orientation="right" domain={["auto", "auto"]} />
              <Tooltip
                contentStyle={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, fontSize: 10 }}
                formatter={(v: number, name: string) => {
                  if (name === "ratio") return [v.toFixed(3), "L/S Ratio"];
                  return [`${Math.abs(v).toFixed(1)}M`, name === "buyVol" ? "Buy Volume" : "Sell Volume"];
                }}
              />
              <Bar yAxisId="vol" dataKey="buyVol" fill="#22c55e" opacity={0.5} />
              <Bar yAxisId="vol" dataKey="sellVol" fill="#ef4444" opacity={0.5} />
              <Line yAxisId="ratio" type="monotone" dataKey="ratio" stroke="#f59e0b" strokeWidth={2} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
