"use client";

import React, { useState, useMemo } from "react";
import {
  AreaChart,
  Area,
  ResponsiveContainer,
  XAxis,
  YAxis,
  Tooltip,
} from "recharts";
import { cn } from "@/lib/utils";
import type { Trade } from "@/types";

interface StrategyStats {
  strategy: string;
  return_pct: number;
  sharpe: number;
  win_rate: number;
  trades: number;
  status: "active" | "backtesting" | "inactive";
  equity: Array<{ date: string; value: number }>;
}

const MEDALS = ["gold", "silver", "bronze"];

function computeStats(trades: Trade[]): StrategyStats[] {
  const stratMap = new Map<string, Trade[]>();
  for (const t of trades) {
    const arr = stratMap.get(t.strategy) || [];
    arr.push(t);
    stratMap.set(t.strategy, arr);
  }

  const result: StrategyStats[] = [];
  const keys = Array.from(stratMap.keys());
  for (let ki = 0; ki < keys.length; ki++) {
    const strategy = keys[ki];
    const stratTrades = stratMap.get(strategy) || [];
    const sorted = [...stratTrades].sort(
      (a, b) => new Date(a.closed_at).getTime() - new Date(b.closed_at).getTime()
    );
    const totalPnlPct = sorted.reduce((s, t) => s + t.pnl_pct, 0);
    const wins = sorted.filter((t) => t.realized_pnl > 0).length;
    const avgReturn = sorted.length > 0 ? totalPnlPct / sorted.length : 0;
    const stdDev = sorted.length > 1
      ? Math.sqrt(sorted.reduce((s, t) => s + Math.pow(t.pnl_pct - avgReturn, 2), 0) / (sorted.length - 1))
      : 1;
    const sharpe = stdDev > 0 ? (avgReturn / stdDev) * Math.sqrt(252) : 0;

    // Build equity curve
    let balance = 10000;
    const equity = sorted.map((t) => {
      balance += t.realized_pnl;
      return {
        date: new Date(t.closed_at).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
        value: balance,
      };
    });

    result.push({
      strategy,
      return_pct: totalPnlPct,
      sharpe,
      win_rate: sorted.length > 0 ? (wins / sorted.length) * 100 : 0,
      trades: sorted.length,
      status: strategy === "ml_ensemble" ? "active" : sorted.length > 20 ? "backtesting" : "inactive",
      equity,
    });
  }

  return result.sort((a, b) => b.return_pct - a.return_pct);
}

export default function StrategyLeaderboard({ trades }: { trades: Trade[] }) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const stats = useMemo(() => computeStats(trades), [trades]);

  if (stats.length === 0) return null;

  return (
    <div className="card">
      <h3 className="section-title mb-3">Strategy Leaderboard</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-left text-xs text-gray-500">
              <th className="pb-2 pr-3 font-medium">Rank</th>
              <th className="pb-2 pr-3 font-medium">Strategy</th>
              <th className="pb-2 pr-3 font-medium">30D Return</th>
              <th className="pb-2 pr-3 font-medium hidden sm:table-cell">Sharpe</th>
              <th className="pb-2 pr-3 font-medium hidden sm:table-cell">Win Rate</th>
              <th className="pb-2 pr-3 font-medium hidden sm:table-cell">Trades</th>
              <th className="pb-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {stats.map((s, i) => (
              <React.Fragment key={s.strategy}>
                <tr
                  className="border-b border-gray-800/50 cursor-pointer hover:bg-gray-800/30 transition-colors"
                  onClick={() => setExpandedIdx(expandedIdx === i ? null : i)}
                >
                  <td className="py-2 pr-3">
                    {i < 3 ? (
                      <span className={cn(
                        "text-sm",
                        i === 0 ? "text-yellow-400" : i === 1 ? "text-gray-300" : "text-amber-600"
                      )}>
                        #{i + 1}
                      </span>
                    ) : (
                      <span className="text-gray-500">#{i + 1}</span>
                    )}
                  </td>
                  <td className="py-2 pr-3 font-medium text-white">{s.strategy}</td>
                  <td className={cn("py-2 pr-3 font-mono", s.return_pct >= 0 ? "text-profit" : "text-loss")}>
                    {s.return_pct >= 0 ? "+" : ""}{s.return_pct.toFixed(2)}%
                  </td>
                  <td className="py-2 pr-3 text-gray-400 hidden sm:table-cell">{s.sharpe.toFixed(1)}</td>
                  <td className="py-2 pr-3 text-gray-400 hidden sm:table-cell">{s.win_rate.toFixed(0)}%</td>
                  <td className="py-2 pr-3 text-gray-400 hidden sm:table-cell">{s.trades}</td>
                  <td className="py-2">
                    <span className={cn(
                      "badge text-[9px]",
                      s.status === "active" ? "bg-green-500/20 text-green-400" :
                      s.status === "backtesting" ? "bg-blue-500/20 text-blue-400" :
                      "bg-gray-500/20 text-gray-400"
                    )}>
                      {s.status}
                    </span>
                  </td>
                </tr>
                {expandedIdx === i && s.equity.length > 0 && (
                  <tr key={`${s.strategy}-chart`}>
                    <td colSpan={7} className="py-2 px-2">
                      <div className="h-[100px] bg-gray-950/50 rounded-lg p-2">
                        <ResponsiveContainer width="100%" height="100%">
                          <AreaChart data={s.equity}>
                            <defs>
                              <linearGradient id={`eq-${i}`} x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#22c55e" stopOpacity={0.2} />
                                <stop offset="100%" stopColor="#22c55e" stopOpacity={0} />
                              </linearGradient>
                            </defs>
                            <XAxis dataKey="date" hide />
                            <YAxis hide domain={["auto", "auto"]} />
                            <Tooltip
                              contentStyle={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, fontSize: 10 }}
                              formatter={(v: number) => [`$${v.toFixed(2)}`, "Equity"]}
                            />
                            <Area type="monotone" dataKey="value" stroke="#22c55e" fill={`url(#eq-${i})`} strokeWidth={1.5} dot={false} />
                          </AreaChart>
                        </ResponsiveContainer>
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
