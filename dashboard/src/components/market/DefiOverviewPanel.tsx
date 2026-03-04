"use client";

import { useQuery } from "@tanstack/react-query";
import { getDefiOverview } from "@/lib/api";
import { formatLargeNumber, cn } from "@/lib/utils";

const CATEGORY_COLORS: Record<string, string> = {
  "Liquid Staking": "bg-blue-500",
  "DEXes": "bg-green-500",
  "Lending": "bg-orange-500",
  "Bridge": "bg-purple-500",
  "CDP": "bg-yellow-500",
  "Restaking": "bg-cyan-500",
};

export default function DefiOverviewPanel() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["defi-overview"],
    queryFn: getDefiOverview,
    refetchInterval: 300000,
  });

  if (isError) return (
    <div className="card text-center py-8">
      <p className="text-sm text-gray-400">Data temporarily unavailable</p>
      <button onClick={() => refetch()} className="mt-2 text-xs text-goblin-500 hover:underline">Retry</button>
    </div>
  );

  if (isLoading || !data) return <div className="card skeleton-shimmer h-64" />;

  const maxTvl = data.top_protocols[0]?.tvl || 1;

  return (
    <div className="card">
      <h3 className="section-title mb-2">DeFi Overview</h3>
      <p className="text-xl font-bold text-white mb-3">{formatLargeNumber(data.total_tvl)} <span className="text-xs text-gray-500 font-normal">Total TVL</span></p>
      <div className="space-y-2">
        {data.top_protocols.map((p) => {
          const barColor = CATEGORY_COLORS[p.category] || "bg-gray-500";
          const width = Math.max(5, (p.tvl / maxTvl) * 100);
          return (
            <div key={p.name}>
              <div className="flex items-center justify-between text-xs mb-0.5">
                <div className="flex items-center gap-1.5">
                  {p.logo && <img src={p.logo} alt={p.name} className="h-4 w-4 rounded-full" />}
                  <span className="text-white font-medium">{p.name}</span>
                  <span className="text-[9px] text-gray-600">{p.category}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-gray-400">{formatLargeNumber(p.tvl)}</span>
                  {p.change_1d !== 0 && (
                    <span className={cn("text-[10px]", (p.change_1d || 0) >= 0 ? "text-profit" : "text-loss")}>
                      {(p.change_1d || 0) >= 0 ? "+" : ""}{(p.change_1d || 0).toFixed(1)}%
                    </span>
                  )}
                </div>
              </div>
              <div className="h-1 rounded-full bg-gray-800">
                <div className={cn("h-1 rounded-full", barColor)} style={{ width: `${width}%` }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
