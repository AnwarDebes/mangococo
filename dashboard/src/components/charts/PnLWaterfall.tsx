"use client";

import { useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  Line,
  ComposedChart,
} from "recharts";
import { formatCurrency } from "@/lib/utils";

interface WaterfallTrade {
  symbol: string;
  pnl: number;
  timestamp: string;
}

interface PnLWaterfallProps {
  trades: Array<WaterfallTrade>;
}
interface WaterfallDataPoint {
  name: string;
  pnl: number;
  base: number;
  cumulative: number;
  isPositive: boolean;
}

function CustomTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: WaterfallDataPoint }>;
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 shadow-lg">
      <p className="text-xs text-gray-400">{d.name}</p>
      <p className={`text-sm font-bold ${d.isPositive ? "text-profit" : "text-loss"}`}>
        {d.pnl >= 0 ? "+" : ""}{formatCurrency(d.pnl)}
      </p>
      <p className="text-xs text-gray-500">
        Cumulative: {formatCurrency(d.cumulative)}
      </p>
    </div>
  );
}
export default function PnLWaterfall({ trades }: PnLWaterfallProps) {
  const chartData = useMemo(() => {
    if (!trades || trades.length === 0) return [];

    const recent = trades.slice(-20);
    let cumulative = 0;
    return recent.map((trade, i) => {
      const base = cumulative;
      cumulative += trade.pnl;
      const isPositive = trade.pnl >= 0;
      return {
        name: trade.symbol || `#${i + 1}`,
        pnl: Math.abs(trade.pnl),
        base: isPositive ? base : base + trade.pnl,
        cumulative,
        isPositive,
        rawPnl: trade.pnl,
      };
    });
  }, [trades]);

  if (chartData.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-gray-500">
        No trade data available
      </div>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={320}>
      <ComposedChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
        <XAxis
          dataKey="name"
          stroke="#6b7280"
          tick={{ fontSize: 10 }}
          tickLine={false}
          angle={-45}
          textAnchor="end"
          height={60}
        />
        <YAxis
          stroke="#6b7280"
          tick={{ fontSize: 11 }}
          tickLine={false}
          tickFormatter={(v: number) => `$${v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(0)}`}
        />
        <Tooltip content={<CustomTooltip />} />
        {/* Invisible base bar (stacking trick) */}
        <Bar dataKey="base" stackId="waterfall" fill="transparent" />
        {/* Visible P&L bar */}
        <Bar dataKey="pnl" stackId="waterfall" radius={[2, 2, 0, 0]}>
          {chartData.map((entry, index) => (
            <Cell
              key={index}
              fill={entry.isPositive ? "#22c55e" : "#ef4444"}
              fillOpacity={0.85}
            />
          ))}
        </Bar>
        {/* Cumulative line */}
        <Line
          type="monotone"
          dataKey="cumulative"
          stroke="#ffc107"
          strokeWidth={2}
          dot={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}