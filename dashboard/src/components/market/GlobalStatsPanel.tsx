"use client";

import { useQuery } from "@tanstack/react-query";
import { PieChart, Pie, Cell, ResponsiveContainer } from "recharts";
import { getGlobalMarket } from "@/lib/api";
import { formatLargeNumber } from "@/lib/utils";

export default function GlobalStatsPanel() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["global-market"],
    queryFn: getGlobalMarket,
    refetchInterval: 60000,
  });

  if (isError) return (
    <div className="card text-center py-8">
      <p className="text-sm text-gray-400">Data temporarily unavailable</p>
      <button onClick={() => refetch()} className="mt-2 text-xs text-goblin-500 hover:underline">Retry</button>
    </div>
  );

  if (isLoading || !data) return <div className="card skeleton-shimmer h-56" />;

  const d = data.data;
  const totalMcap = d.total_market_cap?.usd || 0;
  const totalVol = d.total_volume?.usd || 0;
  const btcDom = d.market_cap_percentage?.btc || 0;
  const ethDom = d.market_cap_percentage?.eth || 0;
  const activeCryptos = d.active_cryptocurrencies || 0;
  const mcapChange = d.market_cap_change_percentage_24h_usd || 0;

  const pieData = [
    { name: "BTC", value: btcDom },
    { name: "ETH", value: ethDom },
    { name: "Others", value: Math.max(0, 100 - btcDom - ethDom) },
  ];
  const COLORS = ["#f59e0b", "#6366f1", "#374151"];

  return (
    <div className="card">
      <h3 className="section-title mb-3">Global Stats</h3>
      <div className="space-y-3">
        <div>
          <p className="text-[10px] text-gray-500">Total Market Cap</p>
          <div className="flex items-baseline gap-2">
            <p className="text-xl font-bold text-white">{formatLargeNumber(totalMcap)}</p>
            <span className={`text-xs font-medium ${mcapChange >= 0 ? "text-profit" : "text-loss"}`}>
              {mcapChange >= 0 ? "+" : ""}{mcapChange.toFixed(1)}%
            </span>
          </div>
        </div>
        <div>
          <p className="text-[10px] text-gray-500">24h Volume</p>
          <p className="text-sm font-bold text-white">{formatLargeNumber(totalVol)}</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="w-16 h-16">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={pieData} dataKey="value" cx="50%" cy="50%" innerRadius={18} outerRadius={28} strokeWidth={0}>
                  {pieData.map((_, i) => (
                    <Cell key={i} fill={COLORS[i]} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="text-xs space-y-0.5">
            <p><span className="text-yellow-400">BTC</span> <span className="text-white font-medium">{btcDom.toFixed(1)}%</span></p>
            <p><span className="text-indigo-400">ETH</span> <span className="text-white font-medium">{ethDom.toFixed(1)}%</span></p>
            <p className="text-gray-500">{activeCryptos.toLocaleString()} coins</p>
          </div>
        </div>
      </div>
    </div>
  );
}
