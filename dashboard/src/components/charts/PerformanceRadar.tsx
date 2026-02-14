"use client";

import { useMemo } from "react";
import {
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

interface PerformanceMetrics {
  sharpe: number;
  sortino: number;
  winRate: number;
  profitFactor: number;
  recoveryFactor: number;
  calmar: number;
}

interface PerformanceRadarProps {
  metrics: PerformanceMetrics;
}
function normalize(value: number, midpoint: number, max: number): number {
  const clamped = Math.max(0, value);
  if (clamped >= max) return 100;
  if (clamped <= 0) return 0;
  if (clamped <= midpoint) {
    return (clamped / midpoint) * 50;
  }
  return 50 + ((clamped - midpoint) / (max - midpoint)) * 50;
}

interface RadarDataPoint {
  metric: string;
  value: number;
  rawValue: string;
  fullMark: number;
}

function CustomTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: RadarDataPoint }>;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 shadow-lg">
      <p className="text-xs text-gray-400">{d.metric}</p>
      <p className="text-sm font-bold text-mango-500">{d.rawValue}</p>
      <p className="text-[10px] text-gray-500">Score: {d.value.toFixed(0)}/100</p>
    </div>
  );
}
export default function PerformanceRadar({ metrics }: PerformanceRadarProps) {
  const chartData = useMemo<RadarDataPoint[]>(() => {
    return [
      {
        metric: "Sharpe",
        value: normalize(metrics.sharpe, 1, 2),
        rawValue: metrics.sharpe.toFixed(2),
        fullMark: 100,
      },
      {
        metric: "Sortino",
        value: normalize(metrics.sortino, 1.5, 3),
        rawValue: metrics.sortino.toFixed(2),
        fullMark: 100,
      },
      {
        metric: "Win Rate",
        value: metrics.winRate * 100,
        rawValue: `${(metrics.winRate * 100).toFixed(1)}%`,
        fullMark: 100,
      },
      {
        metric: "Profit Factor",
        value: normalize(metrics.profitFactor, 1.5, 3),
        rawValue: metrics.profitFactor.toFixed(2),
        fullMark: 100,
      },
      {
        metric: "Recovery",
        value: normalize(metrics.recoveryFactor, 2, 5),
        rawValue: metrics.recoveryFactor.toFixed(2),
        fullMark: 100,
      },
      {
        metric: "Calmar",
        value: normalize(metrics.calmar, 1, 3),
        rawValue: metrics.calmar.toFixed(2),
        fullMark: 100,
      },
    ];
  }, [metrics]);
  return (
    <ResponsiveContainer width="100%" height={320}>
      <RadarChart data={chartData} cx="50%" cy="50%" outerRadius="75%">
        <PolarGrid stroke="#374151" />
        <PolarAngleAxis
          dataKey="metric"
          tick={{ fill: "#e5e7eb", fontSize: 12 }}
          stroke="#4b5563"
        />
        <PolarRadiusAxis
          angle={30}
          domain={[0, 100]}
          tick={{ fill: "#6b7280", fontSize: 9 }}
          stroke="#4b5563"
          tickCount={5}
        />
        <Tooltip content={<CustomTooltip />} />
        <Radar
          name="Performance"
          dataKey="value"
          stroke="#ffc107"
          fill="#ffc107"
          fillOpacity={0.3}
          strokeWidth={2}
        />
      </RadarChart>
    </ResponsiveContainer>
  );
}