"use client";

import { useState, useRef, useCallback, useMemo } from "react";
import {
  AreaChart,
  Area,
  ResponsiveContainer,
} from "recharts";
import { cn, formatCurrency } from "@/lib/utils";
import { Download, Copy } from "lucide-react";
import type { Trade } from "@/types";

interface ReportProps {
  trades: Trade[];
  sharpe: number;
  winRate: number;
  maxDrawdown: number;
  profitFactor: number;
}

export default function PerformanceReport({
  trades,
  sharpe,
  winRate,
  maxDrawdown,
  profitFactor,
}: ReportProps) {
  const [showReport, setShowReport] = useState(false);
  const reportRef = useRef<HTMLDivElement>(null);

  const totalReturn = useMemo(() =>
    trades.reduce((s, t) => s + t.realized_pnl, 0),
    [trades]
  );

  const totalReturnPct = useMemo(() =>
    trades.reduce((s, t) => s + t.pnl_pct, 0),
    [trades]
  );

  // Strategy breakdown
  const strategyBreakdown = useMemo(() => {
    const map = new Map<string, number>();
    trades.forEach((t) => map.set(t.strategy, (map.get(t.strategy) || 0) + 1));
    return Array.from(map.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([strategy, count]) => ({
        strategy,
        pct: trades.length > 0 ? ((count / trades.length) * 100).toFixed(0) : "0",
      }));
  }, [trades]);

  // Monthly returns
  const monthlyReturns = useMemo(() => {
    const map = new Map<string, number>();
    trades.forEach((t) => {
      const month = new Date(t.closed_at).toLocaleDateString("en-US", { year: "numeric", month: "short" });
      map.set(month, (map.get(month) || 0) + t.realized_pnl);
    });
    const sorted = Array.from(map.entries()).sort(
      (a, b) => new Date(a[0]).getTime() - new Date(b[0]).getTime()
    );
    const best = sorted.reduce((best, [m, v]) => v > best.v ? { m, v } : best, { m: "N/A", v: -Infinity });
    const worst = sorted.reduce((worst, [m, v]) => v < worst.v ? { m, v } : worst, { m: "N/A", v: Infinity });
    return { best, worst };
  }, [trades]);

  // Mini equity curve
  const equityData = useMemo(() => {
    let balance = 10000;
    const sorted = [...trades].sort(
      (a, b) => new Date(a.closed_at).getTime() - new Date(b.closed_at).getTime()
    );
    return sorted.map((t) => {
      balance += t.realized_pnl;
      return { value: balance };
    });
  }, [trades]);

  const handleCopy = useCallback(async () => {
    if (!reportRef.current) return;
    try {
      // Fallback: copy text summary
      const text = `Goblin AI Trading Platform - Performance Report
Total Return: ${formatCurrency(totalReturn)} (${totalReturnPct.toFixed(2)}%)
Sharpe Ratio: ${sharpe.toFixed(2)}
Win Rate: ${winRate.toFixed(1)}%
Max Drawdown: ${maxDrawdown.toFixed(2)}%
Total Trades: ${trades.length}
Profit Factor: ${profitFactor === Infinity ? "---" : profitFactor.toFixed(2)}`;
      await navigator.clipboard.writeText(text);
    } catch {
      // ignore
    }
  }, [totalReturn, totalReturnPct, sharpe, winRate, maxDrawdown, trades.length, profitFactor]);

  if (trades.length === 0) return null;

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="section-title">Performance Report</h3>
        <button
          onClick={() => setShowReport(!showReport)}
          className="btn-goblin px-3 py-1 text-xs flex items-center gap-1.5"
        >
          <Download size={13} />
          {showReport ? "Hide Report" : "Generate Report"}
        </button>
      </div>

      {showReport && (
        <div
          ref={reportRef}
          className="rounded-xl border border-goblin-500/20 bg-gray-950 p-5 space-y-4"
        >
          {/* Header */}
          <div className="flex items-center gap-3 border-b border-gray-800 pb-3">
            <div className="h-10 w-10 rounded-full bg-goblin-500/20 flex items-center justify-center">
              <svg width={24} height={24} viewBox="0 0 256 256">
                <ellipse cx="128" cy="140" rx="65" ry="60" fill="#7cb342" />
                <ellipse cx="102" cy="132" rx="14" ry="18" fill="#fff" />
                <ellipse cx="105" cy="134" rx="8" ry="10" fill="#2d2d2d" />
                <ellipse cx="154" cy="132" rx="14" ry="18" fill="#fff" />
                <ellipse cx="157" cy="134" rx="8" ry="10" fill="#2d2d2d" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-bold text-white">Goblin AI Trading Platform</p>
              <p className="text-[10px] text-gray-500">
                Performance Report: {new Date(trades[trades.length - 1]?.created_at || Date.now()).toLocaleDateString()} – {new Date().toLocaleDateString()}
              </p>
            </div>
          </div>

          {/* Key metrics grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {[
              { label: "Total Return", value: `${totalReturnPct >= 0 ? "+" : ""}${totalReturnPct.toFixed(2)}%`, color: totalReturnPct >= 0 ? "text-profit" : "text-loss" },
              { label: "Sharpe Ratio", value: sharpe.toFixed(2), color: sharpe >= 1 ? "text-profit" : "text-white" },
              { label: "Win Rate", value: `${winRate.toFixed(1)}%`, color: "text-goblin-500" },
              { label: "Max Drawdown", value: `${maxDrawdown.toFixed(2)}%`, color: "text-red-400" },
              { label: "Total Trades", value: `${trades.length}`, color: "text-white" },
              { label: "Profit Factor", value: profitFactor === Infinity ? "---" : profitFactor.toFixed(2), color: profitFactor >= 1.5 ? "text-profit" : "text-white" },
            ].map((m) => (
              <div key={m.label} className="text-center p-2 rounded-lg bg-gray-900/50">
                <p className="text-[10px] text-gray-500">{m.label}</p>
                <p className={cn("text-lg font-bold", m.color)}>{m.value}</p>
              </div>
            ))}
          </div>

          {/* Mini equity curve */}
          {equityData.length > 0 && (
            <div className="h-[60px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={equityData}>
                  <defs>
                    <linearGradient id="reportGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#22c55e" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#22c55e" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <Area type="monotone" dataKey="value" stroke="#22c55e" fill="url(#reportGrad)" strokeWidth={1.5} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Strategy breakdown */}
          <div>
            <p className="text-[10px] text-gray-500 mb-1">Strategy Breakdown</p>
            <p className="text-xs text-gray-300">
              {strategyBreakdown.map((s) => `${s.strategy}: ${s.pct}%`).join(", ")}
            </p>
          </div>

          {/* Best / Worst month */}
          <div className="flex gap-4 text-xs">
            <div>
              <span className="text-gray-500">Best Month: </span>
              <span className="text-profit font-bold">{monthlyReturns.best.m} ({formatCurrency(monthlyReturns.best.v)})</span>
            </div>
            <div>
              <span className="text-gray-500">Worst Month: </span>
              <span className="text-loss font-bold">{monthlyReturns.worst.m} ({formatCurrency(monthlyReturns.worst.v)})</span>
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between border-t border-gray-800 pt-2">
            <p className="text-[9px] text-gray-600">
              Generated by Goblin AI &bull; {new Date().toLocaleDateString()}
            </p>
            <button
              onClick={handleCopy}
              className="flex items-center gap-1 text-[10px] text-gray-500 hover:text-white transition-colors"
            >
              <Copy size={11} />
              Copy to Clipboard
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
