"use client";

import { useQuery } from "@tanstack/react-query";
import { AreaChart, Area, ResponsiveContainer } from "recharts";
import { getFearGreed } from "@/lib/api";
import { cn } from "@/lib/utils";

function getColor(value: number): string {
  if (value <= 25) return "#ef4444";
  if (value <= 45) return "#f97316";
  if (value <= 55) return "#eab308";
  if (value <= 75) return "#84cc16";
  return "#22c55e";
}

function GaugeArc({ value }: { value: number }) {
  const angle = (value / 100) * 180;
  const r = 80;
  const cx = 100;
  const cy = 90;

  // Background arc
  const bgEndX = cx + r * Math.cos(Math.PI);
  const bgEndY = cy - r * Math.sin(Math.PI);

  // Value arc
  const rad = ((180 - angle) * Math.PI) / 180;
  const endX = cx + r * Math.cos(rad);
  const endY = cy - r * Math.sin(rad);
  const largeArc = angle > 180 ? 1 : 0;

  const color = getColor(value);

  return (
    <svg viewBox="0 0 200 110" className="w-full max-w-[200px] mx-auto">
      {/* Background arc */}
      <path
        d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
        fill="none"
        stroke="#1f2937"
        strokeWidth="12"
        strokeLinecap="round"
      />
      {/* Value arc */}
      {value > 0 && (
        <path
          d={`M ${cx - r} ${cy} A ${r} ${r} 0 ${largeArc} 1 ${endX} ${endY}`}
          fill="none"
          stroke={color}
          strokeWidth="12"
          strokeLinecap="round"
        />
      )}
      {/* Needle */}
      <circle cx={endX} cy={endY} r="5" fill={color} />
      {/* Center value */}
      <text x={cx} y={cy - 10} textAnchor="middle" className="text-2xl font-bold" fill="white" fontSize="28">
        {value}
      </text>
    </svg>
  );
}

export default function FearGreedPanel() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["fear-greed"],
    queryFn: () => getFearGreed(30),
    refetchInterval: 300000,
  });

  if (isError) return (
    <div className="card text-center py-8">
      <p className="text-sm text-gray-400">Data temporarily unavailable</p>
      <button onClick={() => refetch()} className="mt-2 text-xs text-goblin-500 hover:underline">Retry</button>
    </div>
  );

  if (isLoading || !data) return <div className="card skeleton-shimmer h-56" />;

  const entries = data.data || [];
  const current = entries[0];
  const value = parseInt(current?.value || "50", 10);
  const classification = current?.value_classification || "Neutral";
  const color = getColor(value);

  const chartData = [...entries].reverse().map((d) => ({
    value: parseInt(d.value, 10),
  }));

  return (
    <div className="card">
      <h3 className="section-title mb-3">Fear & Greed Index</h3>
      <GaugeArc value={value} />
      <p className="text-center text-sm font-bold mt-1" style={{ color }}>{classification}</p>
      {chartData.length > 1 && (
        <div className="h-[50px] mt-3">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="fgGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={color} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area type="monotone" dataKey="value" stroke={color} fill="url(#fgGrad)" strokeWidth={1.5} dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
