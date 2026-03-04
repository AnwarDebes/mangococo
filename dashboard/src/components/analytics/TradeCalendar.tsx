"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import type { Trade } from "@/types";

interface Props {
  trades: Trade[];
}

function getDayColor(pnl: number, maxAbsPnl: number): string {
  if (pnl === 0) return "bg-gray-800";
  const intensity = Math.min(Math.abs(pnl) / maxAbsPnl, 1);
  if (pnl > 0) {
    if (intensity > 0.6) return "bg-green-600";
    if (intensity > 0.3) return "bg-green-700/70";
    return "bg-green-800/50";
  }
  if (intensity > 0.6) return "bg-red-600";
  if (intensity > 0.3) return "bg-red-700/70";
  return "bg-red-800/50";
}

export default function TradeCalendar({ trades }: Props) {
  const [tooltip, setTooltip] = useState<{ date: string; count: number; pnl: number; x: number; y: number } | null>(null);

  const { days, maxAbsPnl } = useMemo(() => {
    const dayMap = new Map<string, { count: number; pnl: number }>();
    const now = new Date();

    // Initialize 90 days
    for (let d = 89; d >= 0; d--) {
      const date = new Date(now);
      date.setDate(date.getDate() - d);
      const key = date.toISOString().split("T")[0];
      dayMap.set(key, { count: 0, pnl: 0 });
    }

    // Aggregate trades
    for (const t of trades) {
      const key = new Date(t.closed_at).toISOString().split("T")[0];
      const existing = dayMap.get(key);
      if (existing) {
        existing.count++;
        existing.pnl += t.realized_pnl;
      }
    }

    const entries = Array.from(dayMap.entries()).map(([date, data]) => ({ date, ...data }));
    const maxPnl = Math.max(...entries.map((e) => Math.abs(e.pnl)), 1);
    return { days: entries, maxAbsPnl: maxPnl };
  }, [trades]);

  // Arrange into weeks (7 rows x ~13 cols)
  const weeks: typeof days[] = [];
  let week: typeof days = [];
  const firstDayOfWeek = new Date(days[0]?.date || Date.now()).getDay();
  // Pad the first week
  for (let i = 0; i < firstDayOfWeek; i++) {
    week.push({ date: "", count: 0, pnl: 0 });
  }
  for (const day of days) {
    week.push(day);
    if (week.length === 7) {
      weeks.push(week);
      week = [];
    }
  }
  if (week.length > 0) weeks.push(week);

  return (
    <div className="card relative">
      <h3 className="section-title mb-3">Trade Calendar</h3>
      <div className="flex gap-0.5 flex-wrap">
        {weeks.map((w, wi) => (
          <div key={wi} className="flex flex-col gap-0.5">
            {w.map((day, di) => (
              <div
                key={`${wi}-${di}`}
                className={cn(
                  "w-3 h-3 rounded-sm cursor-default transition-colors",
                  day.date ? getDayColor(day.pnl, maxAbsPnl) : "bg-transparent"
                )}
                onMouseEnter={(e) => day.date && setTooltip({ ...day, x: e.clientX, y: e.clientY })}
                onMouseLeave={() => setTooltip(null)}
              />
            ))}
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2 mt-2 text-[9px] text-gray-500">
        <span>Less</span>
        <div className="flex gap-0.5">
          <div className="w-2.5 h-2.5 rounded-sm bg-red-700/70" />
          <div className="w-2.5 h-2.5 rounded-sm bg-red-800/50" />
          <div className="w-2.5 h-2.5 rounded-sm bg-gray-800" />
          <div className="w-2.5 h-2.5 rounded-sm bg-green-800/50" />
          <div className="w-2.5 h-2.5 rounded-sm bg-green-700/70" />
        </div>
        <span>More</span>
      </div>

      {tooltip && tooltip.date && (
        <div
          className="fixed z-50 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-xs pointer-events-none shadow-xl"
          style={{ left: tooltip.x + 10, top: tooltip.y - 50 }}
        >
          <p className="text-white font-medium">{tooltip.date}</p>
          <p className="text-gray-400">{tooltip.count} trade{tooltip.count !== 1 ? "s" : ""}</p>
          <p className={cn("font-mono", tooltip.pnl >= 0 ? "text-profit" : "text-loss")}>
            {tooltip.pnl >= 0 ? "+" : ""}${tooltip.pnl.toFixed(2)}
          </p>
        </div>
      )}
    </div>
  );
}
