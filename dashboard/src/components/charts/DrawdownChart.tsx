"use client";

import { useMemo } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  ReferenceDot,
} from "recharts";

interface DrawdownDataPoint {
  time: string;
  value: number;
}

interface DrawdownChartProps {
  data: Array<DrawdownDataPoint>;
}
interface DrawdownPoint {
  time: string;
  drawdown: number;
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ value: number }>;
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 shadow-lg">
      <p className="text-xs text-gray-400">{label}</p>
      <p className="text-sm font-bold text-loss">
        {payload[0].value.toFixed(2)}%
      </p>
    </div>
  );
}
export default function DrawdownChart({ data }: DrawdownChartProps) {
  const { chartData, maxDrawdownPoint } = useMemo(() => {
    if (!data || data.length === 0) return { chartData: [], maxDrawdownPoint: null };

    let peak = -Infinity;
    let minDD = 0;
    let minDDIndex = 0;
    const points: DrawdownPoint[] = data.map((d, i) => {
      if (d.value > peak) peak = d.value;
      const dd = peak > 0 ? ((d.value - peak) / peak) * 100 : 0;
      if (dd < minDD) {
        minDD = dd;
        minDDIndex = i;
      }
      return { time: d.time, drawdown: parseFloat(dd.toFixed(2)) };
    });

    const maxDDPoint = points[minDDIndex] || null;
    return { chartData: points, maxDrawdownPoint: maxDDPoint };
  }, [data]);

  if (chartData.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-gray-500">
        No drawdown data available
      </div>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={320}>
      <AreaChart data={chartData}>
        <defs>
          <linearGradient id="drawdownGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="rgba(239,68,68,0.3)" stopOpacity={1} />
            <stop offset="95%" stopColor="rgba(239,68,68,0)" stopOpacity={1} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
        <XAxis
          dataKey="time"
          stroke="#6b7280"
          tick={{ fontSize: 11 }}
          tickLine={false}
        />
        <YAxis
          stroke="#6b7280"
          tick={{ fontSize: 11 }}
          tickLine={false}
          tickFormatter={(v: number) => `${v.toFixed(0)}%`}
          domain={["dataMin", 0]}
        />
        <Tooltip content={<CustomTooltip />} />
        <ReferenceLine y={0} stroke="#6b7280" strokeWidth={2} label={{ value: "Surface", fill: "#9ca3af", fontSize: 10, position: "right" }} />
        <Area
          type="monotone"
          dataKey="drawdown"
          stroke="#ef4444"
          strokeWidth={2}
          fill="url(#drawdownGradient)"
        />
        {maxDrawdownPoint && (
          <ReferenceDot
            x={maxDrawdownPoint.time}
            y={maxDrawdownPoint.drawdown}
            r={5}
            fill="#ef4444"
            stroke="#ffffff"
            strokeWidth={2}
            label={{ value: `Max: ${maxDrawdownPoint.drawdown.toFixed(1)}%`, fill: "#fca5a5", fontSize: 11, position: "bottom" }}
          />
        )}
      </AreaChart>
    </ResponsiveContainer>
  );
}