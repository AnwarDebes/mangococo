"use client";

import { useState } from "react";
import { ArrowUpDown } from "lucide-react";
import {
  formatCurrency,
  formatPrice,
  formatPercent,
  getTimeSince,
  getPnlColor,
  cn,
} from "@/lib/utils";
import type { Trade } from "@/types";

interface TradeHistoryProps {
  trades: Trade[] | undefined;
  isLoading: boolean;
  limit?: number;
}

export default function TradeHistory({
  trades,
  isLoading,
  limit = 10,
}: TradeHistoryProps) {
  const [sortAsc, setSortAsc] = useState(false);

  if (isLoading) {
    return (
      <div className="card animate-pulse space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-8 rounded bg-gray-700" />
        ))}
      </div>
    );
  }

  const sorted = [...(trades || [])].sort((a, b) => {
    const diff =
      new Date(a.closed_at).getTime() - new Date(b.closed_at).getTime();
    return sortAsc ? diff : -diff;
  });

  const display = sorted.slice(0, limit);

  return (
    <div className="card overflow-hidden p-0">
      <div className="flex items-center justify-between border-b border-gray-800 px-5 py-3">
        <h3 className="font-semibold text-white">Recent Trades</h3>
        <button
          onClick={() => setSortAsc(!sortAsc)}
          className="flex items-center gap-1 text-xs text-gray-400 hover:text-white transition-colors"
        >
          <ArrowUpDown size={14} />
          {sortAsc ? "Oldest" : "Newest"}
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-left text-xs text-gray-500">
              <th className="px-5 py-2">Time</th>
              <th className="px-3 py-2">Symbol</th>
              <th className="px-3 py-2">Side</th>
              <th className="px-3 py-2 text-right">Entry</th>
              <th className="px-3 py-2 text-right">Exit</th>
              <th className="px-3 py-2 text-right">PnL</th>
              <th className="px-3 py-2 text-right">PnL%</th>
              <th className="px-3 py-2">Reason</th>
              <th className="px-5 py-2">Strategy</th>
            </tr>
          </thead>
          <tbody>
            {display.length === 0 ? (
              <tr>
                <td
                  colSpan={9}
                  className="px-5 py-8 text-center text-gray-500"
                >
                  No trades yet
                </td>
              </tr>
            ) : (
              display.map((trade, i) => (
                <tr
                  key={i}
                  className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors"
                >
                  <td className="whitespace-nowrap px-5 py-2.5 text-xs text-gray-400">
                    {getTimeSince(trade.closed_at)}
                  </td>
                  <td className="px-3 py-2.5 font-medium text-white">
                    {trade.symbol}
                  </td>
                  <td className="px-3 py-2.5">
                    <span
                      className={cn(
                        "badge",
                        trade.side === "long" ? "badge-buy" : "badge-sell"
                      )}
                    >
                      {trade.side.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-gray-300">
                    ${formatPrice(trade.entry_price)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-gray-300">
                    ${formatPrice(trade.exit_price)}
                  </td>
                  <td
                    className={cn(
                      "px-3 py-2.5 text-right font-mono font-medium",
                      getPnlColor(trade.realized_pnl)
                    )}
                  >
                    {formatCurrency(trade.realized_pnl)}
                  </td>
                  <td
                    className={cn(
                      "px-3 py-2.5 text-right font-mono",
                      getPnlColor(trade.pnl_pct)
                    )}
                  >
                    {formatPercent(trade.pnl_pct)}
                  </td>
                  <td className="px-3 py-2.5 text-xs text-gray-400">
                    {trade.exit_reason}
                  </td>
                  <td className="px-5 py-2.5 text-xs text-gray-400">
                    {trade.strategy}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
