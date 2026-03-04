"use client";

import { useQuery } from "@tanstack/react-query";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { getStablecoins } from "@/lib/api";
import { formatLargeNumber } from "@/lib/utils";

const COLORS = ["#22c55e", "#3b82f6", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4", "#f97316", "#64748b", "#a78bfa", "#34d399"];

export default function StablecoinPanel() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["stablecoins"],
    queryFn: getStablecoins,
    refetchInterval: 300000,
  });

  if (isError) return (
    <div className="card text-center py-8">
      <p className="text-sm text-gray-400">Data temporarily unavailable</p>
      <button onClick={() => refetch()} className="mt-2 text-xs text-goblin-500 hover:underline">Retry</button>
    </div>
  );

  if (isLoading || !data) return <div className="card skeleton-shimmer h-56" />;

  const topStables = data.top_stablecoins || [];
  const chartData = topStables.slice(0, 5).map((s) => ({
    name: s.symbol,
    value: s.supply,
  }));

  return (
    <div className="card">
      <h3 className="section-title mb-2">Stablecoin Supply</h3>
      <p className="text-xl font-bold text-white mb-3">{formatLargeNumber(data.total_supply)}</p>
      <div className="flex items-center gap-4">
        <div className="w-28 h-28">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={chartData} dataKey="value" cx="50%" cy="50%" innerRadius={25} outerRadius={45} strokeWidth={1} stroke="#111827">
                {chartData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, fontSize: 10 }}
                formatter={(v: number) => [formatLargeNumber(v), ""]}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="flex-1 space-y-1">
          {topStables.slice(0, 5).map((s, i) => (
            <div key={s.symbol} className="flex items-center justify-between text-xs">
              <div className="flex items-center gap-1.5">
                <div className="h-2 w-2 rounded-full" style={{ backgroundColor: COLORS[i] }} />
                <span className="text-gray-300">{s.symbol}</span>
              </div>
              <span className="text-gray-400">{formatLargeNumber(s.supply)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
