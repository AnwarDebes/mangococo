"use client";

import { useQuery } from "@tanstack/react-query";
import { BarChart, Bar, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { getDexVolume } from "@/lib/api";
import { formatLargeNumber, cn } from "@/lib/utils";

export default function DexVolumePanel() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["dex-volume"],
    queryFn: getDexVolume,
    refetchInterval: 300000,
  });

  if (isError) return (
    <div className="card text-center py-8">
      <p className="text-sm text-gray-400">Data temporarily unavailable</p>
      <button onClick={() => refetch()} className="mt-2 text-xs text-goblin-500 hover:underline">Retry</button>
    </div>
  );

  if (isLoading || !data) return <div className="card skeleton-shimmer h-56" />;

  const chartData = (data.chart || []).slice(-30).map((entry) => ({
    date: new Date((Array.isArray(entry) ? entry[0] : 0) * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    volume: Array.isArray(entry) ? entry[1] : 0,
  }));

  return (
    <div className="card">
      <h3 className="section-title mb-2">DEX Volume</h3>
      <p className="text-xl font-bold text-white mb-1">{formatLargeNumber(data.total_24h)} <span className="text-xs text-gray-500 font-normal">24h</span></p>

      {chartData.length > 0 && (
        <div className="h-[80px] mb-3">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData}>
              <XAxis dataKey="date" hide />
              <Tooltip
                contentStyle={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, fontSize: 10 }}
                formatter={(v: number) => [formatLargeNumber(v), "Volume"]}
              />
              <Bar dataKey="volume" fill="#7cb342" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="space-y-1.5">
        {(data.top_dexs || []).slice(0, 5).map((dex) => (
          <div key={dex.name} className="flex items-center justify-between text-xs">
            <span className="text-gray-300">{dex.name}</span>
            <div className="flex items-center gap-2">
              <span className="text-gray-400">{formatLargeNumber(dex.volume_24h || 0)}</span>
              {dex.change_1d !== undefined && dex.change_1d !== null && (
                <span className={cn("text-[10px]", (dex.change_1d || 0) >= 0 ? "text-profit" : "text-loss")}>
                  {(dex.change_1d || 0) >= 0 ? "+" : ""}{(dex.change_1d || 0).toFixed(0)}%
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
