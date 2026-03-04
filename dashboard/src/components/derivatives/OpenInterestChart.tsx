"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { AreaChart, Area, ResponsiveContainer, XAxis, YAxis, Tooltip } from "recharts";
import { getOpenInterest } from "@/lib/api";
import { formatLargeNumber, cn } from "@/lib/utils";

const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"];

export default function OpenInterestChart() {
  const [symbol, setSymbol] = useState("BTCUSDT");

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["open-interest", symbol],
    queryFn: () => getOpenInterest(symbol),
    refetchInterval: 60000,
  });

  const chartData = useMemo(() => {
    if (!data?.history) return [];
    return data.history.map((h) => ({
      time: new Date(h.timestamp).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
      value: parseFloat(h.sumOpenInterestValue),
    }));
  }, [data]);

  const currentOI = data?.current ? parseFloat(data.current.openInterest) : 0;
  const currentOIValue = chartData.length > 0 ? chartData[chartData.length - 1]?.value || 0 : 0;

  // Check for leverage building (>5% increase in last 4 entries)
  const leverageBuilding = chartData.length >= 4 &&
    chartData[chartData.length - 1].value > chartData[chartData.length - 4].value * 1.05;

  if (isError) return (
    <div className="card text-center py-8">
      <p className="text-sm text-gray-400">Data temporarily unavailable</p>
      <button onClick={() => refetch()} className="mt-2 text-xs text-goblin-500 hover:underline">Retry</button>
    </div>
  );

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="section-title">Open Interest</h3>
        {leverageBuilding && (
          <span className="badge bg-yellow-500/20 text-yellow-400 text-[9px]">Leverage Building</span>
        )}
      </div>

      {/* Symbol tabs */}
      <div className="flex gap-1 mb-3 overflow-x-auto">
        {SYMBOLS.map((s) => (
          <button
            key={s}
            onClick={() => setSymbol(s)}
            className={cn(
              "px-2 py-1 text-[10px] rounded-md font-medium transition-colors whitespace-nowrap",
              symbol === s ? "bg-gold-500/20 text-gold-400" : "text-gray-500 hover:text-white"
            )}
          >
            {s.replace("USDT", "")}
          </button>
        ))}
      </div>

      <p className="text-lg font-bold text-white mb-2">
        {formatLargeNumber(currentOIValue)}
        <span className="text-xs text-gray-500 font-normal ml-2">{currentOI.toLocaleString()} contracts</span>
      </p>

      {isLoading ? (
        <div className="h-[150px] skeleton-shimmer rounded-lg" />
      ) : (
        <div className="h-[150px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="oiGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.2} />
                  <stop offset="100%" stopColor="#f59e0b" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="time" hide />
              <YAxis hide domain={["auto", "auto"]} />
              <Tooltip
                contentStyle={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, fontSize: 10 }}
                formatter={(v: number) => [formatLargeNumber(v), "OI Value"]}
              />
              <Area type="monotone" dataKey="value" stroke="#f59e0b" fill="url(#oiGrad)" strokeWidth={1.5} dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
