"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { getPredictionCone } from "@/lib/api";
import { cn } from "@/lib/utils";

const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"];

interface ChartPoint {
  index: number;
  label: string;
  price?: number;
  upper?: number;
  mid?: number;
  lower?: number;
  isProjection?: boolean;
}

export default function ProbabilityCone() {
  const [symbol, setSymbol] = useState("BTCUSDT");

  const { data: cone } = useQuery({
    queryKey: ["prediction-cone", symbol],
    queryFn: () => getPredictionCone(symbol),
    refetchInterval: 15000,
  });

  // Build chart data: historical + prediction
  const chartData: ChartPoint[] = [];

  if (cone && cone.historical.length > 0) {
    const hist = cone.historical;
    const step = Math.max(1, Math.floor(hist.length / 30));
    for (let i = 0; i < hist.length; i += step) {
      chartData.push({
        index: chartData.length,
        label: `${hist.length - i}h ago`,
        price: hist[i],
      });
    }
    // Ensure current price is included
    if (chartData.length === 0 || chartData[chartData.length - 1].price !== hist[hist.length - 1]) {
      chartData.push({
        index: chartData.length,
        label: "Now",
        price: hist[hist.length - 1],
      });
    } else {
      chartData[chartData.length - 1].label = "Now";
    }

    const nowIdx = chartData.length - 1;
    const nowPrice = cone.current_price;

    // Add prediction points
    const projPoints = [
      { label: "+1h", data: cone.cone["1h"] },
      { label: "+4h", data: cone.cone["4h"] },
      { label: "+24h", data: cone.cone["24h"] },
    ];

    for (const p of projPoints) {
      chartData.push({
        index: chartData.length,
        label: p.label,
        upper: p.data.upper,
        mid: p.data.mid,
        lower: p.data.lower,
        isProjection: true,
      });
    }

    // Bridge: current price connects to first projection
    chartData[nowIdx].upper = nowPrice;
    chartData[nowIdx].mid = nowPrice;
    chartData[nowIdx].lower = nowPrice;
  }

  const isUp = cone?.prediction.direction === "up";
  const fillColor = isUp ? "rgba(34,197,94,0.12)" : "rgba(239,68,68,0.12)";
  const strokeColor = isUp ? "#22c55e" : "#ef4444";
  const confidence = cone?.prediction.confidence ?? 0;
  const nowIndex = chartData.findIndex((d) => d.label === "Now");

  return (
    <div className="flex h-full flex-col">
      {/* Symbol tabs */}
      <div className="flex items-center gap-1 mb-2">
        {SYMBOLS.map((s) => (
          <button
            key={s}
            onClick={() => setSymbol(s)}
            className={cn(
              "px-3 py-1 text-xs font-medium rounded-lg transition-colors",
              symbol === s
                ? "bg-goblin-500/20 text-goblin-400 border border-goblin-500/30"
                : "text-gray-500 hover:text-gray-300"
            )}
          >
            {s.replace("USDT", "/USDT")}
          </button>
        ))}
        {cone && (
          <div className="ml-auto flex items-center gap-2">
            <span className={cn("text-xs font-bold uppercase", isUp ? "text-profit" : "text-loss")}>
              {cone.prediction.direction}
            </span>
            <span className="text-xs text-gray-500">
              {(confidence * 100).toFixed(0)}% confidence
            </span>
          </div>
        )}
      </div>

      {/* Price display */}
      {cone && (
        <div className="mb-2 flex items-baseline gap-2">
          <span className="text-2xl font-bold text-white">
            ${cone.current_price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
          <span className="text-xs text-gray-500">{symbol.replace("USDT", "/USDT")}</span>
        </div>
      )}

      {/* Chart */}
      <div className="flex-1 min-h-0">
        {chartData.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-gray-500">
            Loading prediction data...
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 0 }}>
              <defs>
                <linearGradient id="coneFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={strokeColor} stopOpacity={0.15} />
                  <stop offset="100%" stopColor={strokeColor} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="label"
                tick={{ fontSize: 10, fill: "#6b7280" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                domain={["auto", "auto"]}
                tick={{ fontSize: 10, fill: "#6b7280" }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v: number) => `$${v.toLocaleString()}`}
                width={75}
              />
              <Tooltip
                contentStyle={{
                  background: "#111827",
                  border: "1px solid #1f2937",
                  borderRadius: 8,
                  fontSize: 11,
                }}
                formatter={(value: number, name: string) => {
                  const label = name === "price" ? "Price" : name === "mid" ? "Predicted" : name === "upper" ? "Upper" : "Lower";
                  return [`$${value.toLocaleString(undefined, { minimumFractionDigits: 2 })}`, label];
                }}
              />
              {nowIndex >= 0 && (
                <ReferenceLine
                  x={chartData[nowIndex].label}
                  stroke="#6b7280"
                  strokeDasharray="3 3"
                  strokeWidth={1}
                />
              )}
              {/* Historical price line */}
              <Area
                type="monotone"
                dataKey="price"
                stroke="#ffffff"
                strokeWidth={2}
                fill="none"
                dot={false}
                animationDuration={500}
              />
              {/* Cone bands */}
              <Area
                type="monotone"
                dataKey="upper"
                stroke={strokeColor}
                strokeWidth={1}
                strokeDasharray="4 2"
                fill="url(#coneFill)"
                dot={false}
                animationDuration={700}
              />
              <Area
                type="monotone"
                dataKey="mid"
                stroke={strokeColor}
                strokeWidth={2}
                strokeDasharray="6 3"
                fill="none"
                dot={false}
                animationDuration={700}
              />
              <Area
                type="monotone"
                dataKey="lower"
                stroke={strokeColor}
                strokeWidth={1}
                strokeDasharray="4 2"
                fill="none"
                dot={false}
                animationDuration={700}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
