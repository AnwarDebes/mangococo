"use client";

import { useState, useMemo, useCallback } from "react";

interface CalendarDataPoint {
  date: string;
  pnl: number;
  trades: number;
}

interface MonthlyReturnsCalendarProps {
  data: Array<CalendarDataPoint>;
}

interface TooltipState {
  x: number;
  y: number;
  date: string;
  pnl: number;
  trades: number;
}

const CELL_SIZE = 14;
const CELL_GAP = 2;
const STEP = CELL_SIZE + CELL_GAP;const DAY_LABELS = ["M", "", "W", "", "F", "", ""];
const MONTH_NAMES = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function getPnlColor(pnl: number): string {
  if (pnl <= -5) return "#dc2626";
  if (pnl <= -3) return "#ef4444";
  if (pnl <= -1) return "#fca5a5";
  if (pnl < -0.01) return "#fecaca";
  if (Math.abs(pnl) < 0.01) return "#374151";
  if (pnl <= 1) return "#bbf7d0";
  if (pnl <= 3) return "#86efac";
  if (pnl < 5) return "#4ade80";
  return "#16a34a";
}

function buildDateMap(data: CalendarDataPoint[]): Map<string, CalendarDataPoint> {
  const map = new Map<string, CalendarDataPoint>();
  for (const d of data) {
    map.set(d.date, d);
  }
  return map;
}
export default function MonthlyReturnsCalendar({ data }: MonthlyReturnsCalendarProps) {
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  const { cells, monthLabels, totalWeeks } = useMemo(() => {
    const dateMap = buildDateMap(data);
    const now = new Date();
    const startDate = new Date(now);
    startDate.setDate(startDate.getDate() - 364);
    const dayOfWeek = startDate.getDay();
    startDate.setDate(startDate.getDate() - dayOfWeek);

    const cellList: Array<{
      week: number;
      day: number;
      date: string;
      pnl: number;
      trades: number;
      hasData: boolean;
    }> = [];
    const monthLabelList: Array<{ week: number; label: string }> = [];
    let lastMonth = -1;
    let weekIndex = 0;
    const current = new Date(startDate);
    while (current <= now || weekIndex < 53) {
      if (weekIndex >= 53) break;
      for (let dayIdx = 0; dayIdx < 7; dayIdx++) {
        const dateStr = current.toISOString().split("T")[0];
        const entry = dateMap.get(dateStr);
        const month = current.getMonth();
        if (month !== lastMonth && dayIdx === 0) {
          monthLabelList.push({ week: weekIndex, label: MONTH_NAMES[month] });
          lastMonth = month;
        }
        cellList.push({
          week: weekIndex,
          day: dayIdx,
          date: dateStr,
          pnl: entry?.pnl ?? 0,
          trades: entry?.trades ?? 0,
          hasData: !!entry,
        });
        current.setDate(current.getDate() + 1);
      }
      weekIndex++;
    }
    return { cells: cellList, monthLabels: monthLabelList, totalWeeks: weekIndex };
  }, [data]);
  const handleMouseEnter = useCallback(
    (e: React.MouseEvent<SVGRectElement>, cell: (typeof cells)[0]) => {
      if (!cell.hasData) return;
      const rect = e.currentTarget.getBoundingClientRect();
      setTooltip({
        x: rect.left + rect.width / 2,
        y: rect.top,
        date: cell.date,
        pnl: cell.pnl,
        trades: cell.trades,
      });
    },
    []
  );

  const handleMouseLeave = useCallback(() => {
    setTooltip(null);
  }, []);

  const LEFT_PADDING = 28;
  const TOP_PADDING = 20;
  const svgWidth = LEFT_PADDING + totalWeeks * STEP + 4;
  const svgHeight = TOP_PADDING + 7 * STEP + 4;
  return (
    <div className="relative">
      <div className="overflow-x-auto">
        <svg width={svgWidth} height={svgHeight} className="block" style={{ minWidth: svgWidth }}>
          {monthLabels.map((ml, i) => (
            <text key={i} x={LEFT_PADDING + ml.week * STEP + CELL_SIZE / 2} y={12} fill="#9ca3af" fontSize="10" textAnchor="middle">
              {ml.label}
            </text>
          ))}
          {DAY_LABELS.map((label, i) =>
            label ? (
              <text key={i} x={LEFT_PADDING - 6} y={TOP_PADDING + i * STEP + CELL_SIZE / 2 + 4} fill="#6b7280" fontSize="9" textAnchor="end">
                {label}
              </text>
            ) : null
          )}
          {cells.map((cell, i) => (
            <rect
              key={i}
              x={LEFT_PADDING + cell.week * STEP}
              y={TOP_PADDING + cell.day * STEP}
              width={CELL_SIZE}
              height={CELL_SIZE}
              rx={2}
              fill={cell.hasData ? getPnlColor(cell.pnl) : "#1f2937"}
              opacity={cell.hasData ? 1 : 0.3}
              className="cursor-pointer transition-opacity hover:opacity-80"
              onMouseEnter={(e) => handleMouseEnter(e, cell)}
              onMouseLeave={handleMouseLeave}
            />
          ))}
        </svg>
      </div>
      {tooltip && (
        <div
          className="pointer-events-none fixed z-50 rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 shadow-lg"
          style={{ left: tooltip.x, top: tooltip.y - 8, transform: "translate(-50%, -100%)" }}
        >
          <p className="text-xs text-gray-400">{tooltip.date}</p>
          <p className={`text-sm font-bold ${tooltip.pnl >= 0 ? "text-profit" : "text-loss"}`}>
            {tooltip.pnl >= 0 ? "+" : ""}{tooltip.pnl.toFixed(2)}%
          </p>
          <p className="text-xs text-gray-500">{tooltip.trades} trades</p>
        </div>
      )}

      <div className="mt-2 flex items-center justify-end gap-1 text-xs text-gray-500">
        <span>Less</span>
        {["#dc2626", "#fca5a5", "#374151", "#86efac", "#16a34a"].map((color, i) => (
          <div key={i} className="h-3 w-3 rounded-sm" style={{ backgroundColor: color }} />
        ))}
        <span>More</span>
      </div>
    </div>
  );
}