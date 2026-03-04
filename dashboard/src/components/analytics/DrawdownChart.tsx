"use client";

import { useMemo } from "react";
import { AreaChart, Area, ResponsiveContainer, XAxis, YAxis, Tooltip, ReferenceLine } from "recharts";
import { cn } from "@/lib/utils";
import type { Trade } from "@/types";

interface Props {
  trades: Trade[];
}

export default function DrawdownChart({ trades }: Props) {
  const { chartData, maxDrawdown, maxDrawdownDate } = useMemo(() => {
    if (!trades || trades.length === 0) return { chartData: [], maxDrawdown: 0, maxDrawdownDate: "" };

    const sorted = [...trades].sort(
      (a, b) => new Date(a.closed_at).getTime() - new Date(b.closed_at).getTime()
    );

    let balance = 10000;
    let peak = balance;
    let worstDrawdown = 0;
    let worstDate = "";

    const points = sorted.map((t) => {
      balance += t.realized_pnl;
      if (balance > peak) peak = balance;
      const dd = peak > 0 ? ((balance - peak) / peak) * 100 : 0;
      if (dd < worstDrawdown) {
        worstDrawdown = dd;
        worstDate = new Date(t.closed_at).toLocaleDateString("en-US", { month: "short", day: "numeric" });
      }
      return {
        date: new Date(t.closed_at).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
        drawdown: Math.round(dd * 100) / 100,
      };
    });

    return { chartData: points, maxDrawdown: worstDrawdown, maxDrawdownDate: worstDate };
  }, [trades]);

  if (chartData.length === 0) return null;

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="section-title">Drawdown Analysis</h3>
        {maxDrawdown < 0 && (
          <span className="text-xs text-red-400 font-mono">
            Max: {maxDrawdown.toFixed(1)}% on {maxDrawdownDate}
          </span>
        )}
      </div>
      <div className="h-[160px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#ef4444" stopOpacity={0} />
                <stop offset="100%" stopColor="#ef4444" stopOpacity={0.3} />
              </linearGradient>
            </defs>
            <XAxis dataKey="date" hide />
            <YAxis hide domain={["auto", 0]} />
            <Tooltip
              contentStyle={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, fontSize: 10 }}
              formatter={(v: number) => [`${v.toFixed(2)}%`, "Drawdown"]}
            />
            <ReferenceLine y={0} stroke="#374151" strokeWidth={1} />
            <Area type="monotone" dataKey="drawdown" stroke="#ef4444" fill="url(#ddGrad)" strokeWidth={1.5} dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
