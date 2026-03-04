"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip, Legend } from "recharts";
import { getBenchmark } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Trade } from "@/types";

interface Props {
  trades: Trade[];
}

export default function BenchmarkComparison({ trades }: Props) {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["benchmark"],
    queryFn: () => getBenchmark(90),
    refetchInterval: 300000,
  });

  const portfolioSeries = useMemo(() => {
    if (!trades || trades.length === 0 || !data) return [];
    let balance = 100;
    const sorted = [...trades].sort(
      (a, b) => new Date(a.closed_at).getTime() - new Date(b.closed_at).getTime()
    );
    const startBalance = 10000;
    const dailyMap = new Map<string, number>();
    let runBal = startBalance;
    for (const t of sorted) {
      runBal += t.realized_pnl;
      const day = new Date(t.closed_at).toISOString().split("T")[0];
      dailyMap.set(day, runBal);
    }
    // Normalize to 100 base
    const firstVal = sorted.length > 0 ? startBalance : 100;
    const result: number[] = [];
    const dates = data.dates || [];
    let lastVal = firstVal;
    for (const d of dates) {
      const v = dailyMap.get(d);
      if (v !== undefined) lastVal = v;
      result.push(Math.round((lastVal / firstVal) * 100 * 100) / 100);
    }
    return result;
  }, [trades, data]);

  if (isError) return (
    <div className="card text-center py-8">
      <p className="text-sm text-gray-400">Data temporarily unavailable</p>
      <button onClick={() => refetch()} className="mt-2 text-xs text-goblin-500 hover:underline">Retry</button>
    </div>
  );

  if (isLoading || !data) return <div className="card skeleton-shimmer h-56" />;

  const chartData = (data.dates || []).map((d, i) => ({
    date: d,
    btc: data.btc[i] || 100,
    eth: data.eth[i] || 100,
    portfolio: portfolioSeries[i] || 100,
  }));

  const lastPortfolio = chartData.length > 0 ? chartData[chartData.length - 1].portfolio : 100;
  const lastBtc = chartData.length > 0 ? chartData[chartData.length - 1].btc : 100;
  const lastEth = chartData.length > 0 ? chartData[chartData.length - 1].eth : 100;

  return (
    <div className="card">
      <h3 className="section-title mb-3">Benchmark Comparison</h3>

      <div className="flex gap-4 mb-3 text-xs">
        <div>
          <span className="text-gray-500">vs BTC: </span>
          <span className={cn("font-mono font-medium", lastPortfolio - lastBtc >= 0 ? "text-profit" : "text-loss")}>
            {lastPortfolio - lastBtc >= 0 ? "+" : ""}{(lastPortfolio - lastBtc).toFixed(1)}%
          </span>
        </div>
        <div>
          <span className="text-gray-500">vs ETH: </span>
          <span className={cn("font-mono font-medium", lastPortfolio - lastEth >= 0 ? "text-profit" : "text-loss")}>
            {lastPortfolio - lastEth >= 0 ? "+" : ""}{(lastPortfolio - lastEth).toFixed(1)}%
          </span>
        </div>
      </div>

      <div className="h-[200px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData}>
            <XAxis dataKey="date" hide />
            <YAxis hide domain={["auto", "auto"]} />
            <Tooltip
              contentStyle={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, fontSize: 10 }}
              formatter={(v: number, name: string) => [`${v.toFixed(1)}`, name]}
            />
            <Legend iconSize={8} wrapperStyle={{ fontSize: 10 }} />
            <Line type="monotone" dataKey="portfolio" stroke="#7cb342" strokeWidth={2} dot={false} name="Portfolio" />
            <Line type="monotone" dataKey="btc" stroke="#f59e0b" strokeWidth={1.5} dot={false} name="BTC" strokeDasharray="4 2" />
            <Line type="monotone" dataKey="eth" stroke="#6b7280" strokeWidth={1.5} dot={false} name="ETH" strokeDasharray="4 2" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
