"use client";

import { useQuery } from "@tanstack/react-query";
import { getTrending } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function TrendingPanel() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["trending"],
    queryFn: getTrending,
    refetchInterval: 300000,
  });

  if (isError) return (
    <div className="card text-center py-8">
      <p className="text-sm text-gray-400">Data temporarily unavailable</p>
      <button onClick={() => refetch()} className="mt-2 text-xs text-goblin-500 hover:underline">Retry</button>
    </div>
  );

  if (isLoading || !data) return <div className="card skeleton-shimmer h-56" />;

  const coins = data.coins || [];

  return (
    <div className="card">
      <h3 className="section-title mb-3">Trending Coins</h3>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {coins.slice(0, 9).map((c, i) => {
          const item = c.item;
          const change24h = item.data?.price_change_percentage_24h?.usd;
          return (
            <div key={item.id} className="flex items-center gap-2 p-2 rounded-lg bg-gray-900/50 hover:bg-gray-800/50 transition-colors">
              <span className={cn(
                "text-xs font-bold w-5 text-center",
                i < 3 ? "text-gold-500" : "text-gray-500"
              )}>
                {i + 1}
              </span>
              {item.thumb && <img src={item.thumb} alt={item.symbol} className="h-5 w-5 rounded-full" />}
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-white truncate">{item.name}</p>
                <p className="text-[10px] text-gray-500">{item.symbol} {item.market_cap_rank ? `#${item.market_cap_rank}` : ""}</p>
              </div>
              {change24h !== undefined && (
                <span className={cn("text-[10px] font-mono", change24h >= 0 ? "text-profit" : "text-loss")}>
                  {change24h >= 0 ? "+" : ""}{change24h.toFixed(1)}%
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
