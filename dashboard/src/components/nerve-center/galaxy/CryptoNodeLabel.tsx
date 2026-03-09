"use client";

import { Html } from "@react-three/drei";

interface CryptoNodeLabelProps {
  symbol: string;
  price: string;
  change: string;
  volume?: string;
  sentimentScore?: number;
}

export default function CryptoNodeLabel({ symbol, price, change, volume, sentimentScore }: CryptoNodeLabelProps) {
  const changeNum = parseFloat(change);
  const changeColor = changeNum > 0 ? "text-green-400" : changeNum < 0 ? "text-red-400" : "text-gray-400";
  const priceNum = parseFloat(price);
  const priceStr = priceNum >= 1
    ? `$${priceNum.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
    : `$${priceNum.toFixed(6)}`;

  const volStr = volume ? formatVolume(parseFloat(volume)) : null;

  const sentColor = sentimentScore != null
    ? sentimentScore > 60 ? "#22c55e" : sentimentScore < 40 ? "#ef4444" : "#f59e0b"
    : null;

  return (
    <Html distanceFactor={8} style={{ pointerEvents: "none" }}>
      <div className="text-center whitespace-nowrap select-none bg-black/50 rounded-md px-2 py-1 backdrop-blur-sm border border-white/10">
        <div className="text-sm font-bold text-white">{symbol.replace("USDT", "")}</div>
        <div className="text-xs text-gray-200">{priceStr}</div>
        <div className={`text-xs font-semibold ${changeColor}`}>
          {changeNum > 0 ? "+" : ""}{changeNum.toFixed(2)}%
        </div>
        {volStr && <div className="text-[10px] text-gray-400">Vol: {volStr}</div>}
        {sentColor && sentimentScore != null && (
          <div className="mt-0.5 w-full h-1 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full"
              style={{ width: `${sentimentScore}%`, backgroundColor: sentColor }}
            />
          </div>
        )}
      </div>
    </Html>
  );
}

function formatVolume(v: number): string {
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toFixed(0);
}
