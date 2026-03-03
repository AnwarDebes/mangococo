"use client";

import { useQuery } from "@tanstack/react-query";
import { getWhaleActivity } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ArrowUpRight, ArrowDownLeft } from "lucide-react";

function formatAmount(usd: number): string {
  if (usd >= 1_000_000_000) return `$${(usd / 1_000_000_000).toFixed(1)}B`;
  if (usd >= 1_000_000) return `$${(usd / 1_000_000).toFixed(1)}M`;
  if (usd >= 1_000) return `$${(usd / 1_000).toFixed(0)}K`;
  return `$${usd.toFixed(0)}`;
}

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function WhaleSvg({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cn("h-4 w-4", className)} fill="none" stroke="currentColor" strokeWidth={1.5}>
      <path d="M3 14c0-3 2-6 6-7 2-.5 4 0 6 1 3 2 5 4 6 6-1 1-3 2-5 2H8c-3 0-5-1-5-2z" />
      <circle cx="7" cy="11" r="1" fill="currentColor" />
      <path d="M19 14c1 2 2 3 2 5" strokeLinecap="round" />
    </svg>
  );
}

export default function WhaleActivityFeed() {
  const { data } = useQuery({
    queryKey: ["whales"],
    queryFn: () => getWhaleActivity(20),
    refetchInterval: 30000,
  });

  const transactions = data?.transactions ?? [];
  const summary = data?.summary;

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="section-title flex items-center gap-2">
          <WhaleSvg className="text-blue-400" />
          Whale Activity
        </h3>
        {summary && (
          <span className={cn(
            "badge text-[10px]",
            summary.whale_sentiment === "accumulation" ? "bg-green-500/20 text-green-400" :
            summary.whale_sentiment === "distribution" ? "bg-red-500/20 text-red-400" :
            "bg-gray-500/20 text-gray-400"
          )}>
            {summary.whale_sentiment}
          </span>
        )}
      </div>

      {/* Transaction feed */}
      <div className="max-h-[350px] overflow-y-auto space-y-2">
        {transactions.length === 0 ? (
          <p className="text-sm text-gray-500 text-center py-6">No whale activity detected</p>
        ) : (
          transactions.map((tx, i) => {
            const isOutflow = tx.direction === "exchange_outflow";
            const ArrowIcon = isOutflow ? ArrowUpRight : ArrowDownLeft;
            return (
              <div
                key={`${tx.timestamp}-${i}`}
                className={cn(
                  "flex items-start gap-3 p-2.5 rounded-lg transition-all animate-fade-in",
                  isOutflow ? "bg-green-500/5 border border-green-500/10" : "bg-red-500/5 border border-red-500/10"
                )}
                style={{ animationDelay: `${i * 50}ms` }}
              >
                <div className={cn(
                  "shrink-0 mt-0.5 rounded-full p-1.5",
                  isOutflow ? "bg-green-500/20" : "bg-red-500/20"
                )}>
                  <ArrowIcon size={14} className={isOutflow ? "text-green-400" : "text-red-400"} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-bold text-white">
                      {formatAmount(tx.amount_usd)}
                    </span>
                    <span className="text-xs text-gray-400">{tx.symbol.replace("/USDT", "")}</span>
                    <span className={cn(
                      "badge text-[9px] ml-auto",
                      tx.significance === "bullish" ? "bg-green-500/20 text-green-400" :
                      tx.significance === "bearish" ? "bg-red-500/20 text-red-400" :
                      "bg-gray-500/20 text-gray-400"
                    )}>
                      {tx.significance}
                    </span>
                  </div>
                  <p className="text-[10px] text-gray-500 mt-0.5">
                    {tx.from_label} → {tx.to_label}
                  </p>
                  <p className="text-[9px] text-gray-600 mt-0.5">{timeAgo(tx.timestamp)}</p>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Net Exchange Flow */}
      {summary && (
        <div className="mt-4 pt-3 border-t border-gray-800">
          <p className="text-xs text-gray-500 mb-2">Net Exchange Flow</p>
          <div className="space-y-2">
            {[
              { label: "BTC", value: summary.net_exchange_flow_btc },
              { label: "ETH", value: summary.net_exchange_flow_eth },
            ].map(({ label, value }) => {
              const pct = Math.min(Math.abs(value) / 100, 100);
              const isPositive = value > 0;
              return (
                <div key={label} className="flex items-center gap-2">
                  <span className="text-xs text-gray-400 w-8">{label}</span>
                  <div className="flex-1 flex items-center">
                    <div className="w-1/2 flex justify-end">
                      {!isPositive && (
                        <div
                          className="h-2 rounded-l-full bg-red-500/60"
                          style={{ width: `${pct}%` }}
                        />
                      )}
                    </div>
                    <div className="w-px h-4 bg-gray-600 mx-0.5" />
                    <div className="w-1/2">
                      {isPositive && (
                        <div
                          className="h-2 rounded-r-full bg-green-500/60"
                          style={{ width: `${pct}%` }}
                        />
                      )}
                    </div>
                  </div>
                  <span className={cn("text-[10px] font-mono w-16 text-right", isPositive ? "text-green-400" : "text-red-400")}>
                    {isPositive ? "+" : ""}{value.toFixed(0)}
                  </span>
                </div>
              );
            })}
          </div>
          <p className="text-[10px] text-gray-500 mt-2 text-center">
            Whales are currently in <span className={cn(
              "font-bold",
              summary.whale_sentiment === "accumulation" ? "text-green-400" : "text-red-400"
            )}>{summary.whale_sentiment}</span> mode
          </p>
        </div>
      )}
    </div>
  );
}
