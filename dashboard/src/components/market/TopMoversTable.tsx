"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { LineChart, Line, ResponsiveContainer } from "recharts";
import { getTopCoins } from "@/lib/api";
import { cn, formatLargeNumber } from "@/lib/utils";
import type { TopCoin } from "@/types";

type SortKey = "market_cap_rank" | "current_price" | "price_change_percentage_24h_in_currency" | "market_cap";

export default function TopMoversTable() {
  const [sortKey, setSortKey] = useState<SortKey>("market_cap_rank");
  const [sortAsc, setSortAsc] = useState(true);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["top-coins"],
    queryFn: () => getTopCoins(20),
    refetchInterval: 60000,
  });

  const sorted = useMemo(() => {
    if (!data) return [];
    const arr = [...data];
    arr.sort((a, b) => {
      const av = a[sortKey] ?? 0;
      const bv = b[sortKey] ?? 0;
      return sortAsc ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1);
    });
    return arr;
  }, [data, sortKey, sortAsc]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(true); }
  };

  if (isError) return (
    <div className="card text-center py-8">
      <p className="text-sm text-gray-400">Data temporarily unavailable</p>
      <button onClick={() => refetch()} className="mt-2 text-xs text-goblin-500 hover:underline">Retry</button>
    </div>
  );

  if (isLoading) return <div className="card skeleton-shimmer h-64" />;

  const PctCell = ({ value }: { value: number | undefined }) => {
    const v = value ?? 0;
    return (
      <span className={cn("font-mono", v >= 0 ? "text-profit" : "text-loss")}>
        {v >= 0 ? "+" : ""}{v.toFixed(1)}%
      </span>
    );
  };

  return (
    <div className="card">
      <h3 className="section-title mb-3">Top Movers</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-left text-xs text-gray-500">
              <th className="pb-2 pr-2 font-medium cursor-pointer" onClick={() => handleSort("market_cap_rank")}>#</th>
              <th className="pb-2 pr-3 font-medium">Coin</th>
              <th className="pb-2 pr-3 font-medium cursor-pointer" onClick={() => handleSort("current_price")}>Price</th>
              <th className="pb-2 pr-3 font-medium hidden sm:table-cell">1h%</th>
              <th className="pb-2 pr-3 font-medium cursor-pointer" onClick={() => handleSort("price_change_percentage_24h_in_currency")}>24h%</th>
              <th className="pb-2 pr-3 font-medium hidden sm:table-cell">7d%</th>
              <th className="pb-2 pr-3 font-medium hidden sm:table-cell cursor-pointer" onClick={() => handleSort("market_cap")}>Market Cap</th>
              <th className="pb-2 font-medium">7d</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((coin) => {
              const sparkPrices = coin.sparkline_in_7d?.price || [];
              const sparkData = sparkPrices.filter((_, i) => i % 6 === 0).map((p) => ({ v: p }));
              const isUp = sparkPrices.length > 1 && sparkPrices[sparkPrices.length - 1] >= sparkPrices[0];

              return (
                <tr key={coin.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                  <td className="py-2 pr-2 text-gray-500">{coin.market_cap_rank}</td>
                  <td className="py-2 pr-3">
                    <div className="flex items-center gap-2">
                      {coin.image && <img src={coin.image} alt={coin.symbol} className="h-5 w-5 rounded-full" />}
                      <span className="font-medium text-white">{coin.name}</span>
                      <span className="text-gray-500 uppercase text-xs">{coin.symbol}</span>
                    </div>
                  </td>
                  <td className="py-2 pr-3 font-mono text-white">${coin.current_price?.toLocaleString()}</td>
                  <td className="py-2 pr-3 hidden sm:table-cell"><PctCell value={coin.price_change_percentage_1h_in_currency} /></td>
                  <td className="py-2 pr-3"><PctCell value={coin.price_change_percentage_24h_in_currency} /></td>
                  <td className="py-2 pr-3 hidden sm:table-cell"><PctCell value={coin.price_change_percentage_7d_in_currency} /></td>
                  <td className="py-2 pr-3 hidden sm:table-cell text-gray-400">{formatLargeNumber(coin.market_cap || 0)}</td>
                  <td className="py-2">
                    {sparkData.length > 2 && (
                      <div className="w-[80px] h-[30px]">
                        <ResponsiveContainer width="100%" height="100%">
                          <LineChart data={sparkData}>
                            <Line type="monotone" dataKey="v" stroke={isUp ? "#22c55e" : "#ef4444"} strokeWidth={1} dot={false} />
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
