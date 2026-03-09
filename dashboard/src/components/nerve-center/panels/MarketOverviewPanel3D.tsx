"use client";

import { Html } from "@react-three/drei";
import type { FearGreedData, GlobalMarketData } from "@/types";

interface MarketOverviewPanel3DProps {
  fearGreed?: FearGreedData;
  globalMarket?: GlobalMarketData;
  position: [number, number, number];
}

export default function MarketOverviewPanel3D({ fearGreed, globalMarket, position }: MarketOverviewPanel3DProps) {
  const fgRaw = fearGreed?.data?.[0]?.value ?? null;
  const fgValue = fgRaw != null ? Number(fgRaw) : null;
  const fgLabel = fearGreed?.data?.[0]?.value_classification ?? "";
  const fgColor = fgValue != null
    ? fgValue <= 25 ? "#ef4444" : fgValue <= 45 ? "#f59e0b" : fgValue <= 55 ? "#6b7280" : fgValue <= 75 ? "#22c55e" : "#22c55e"
    : "#6b7280";

  const marketData = globalMarket?.data;
  const totalMcap = marketData?.total_market_cap?.usd;
  const btcDom = marketData?.market_cap_percentage?.btc;
  const ethDom = marketData?.market_cap_percentage?.eth;
  const mcapChange = marketData?.market_cap_change_percentage_24h_usd;

  return (
    <Html position={position} distanceFactor={12} style={{ pointerEvents: "none" }}>
      <div className="bg-gray-900/90 border border-blue-500/20 rounded-lg p-3 w-56 backdrop-blur select-none">
        <div className="text-xs font-bold text-blue-400 mb-2">Market Overview</div>
        <div className="space-y-1.5 text-[11px]">
          {fgValue != null && (
            <div className="flex justify-between items-center">
              <span className="text-gray-400">Fear & Greed</span>
              <span style={{ color: fgColor }} className="font-bold">
                {fgValue} <span className="font-normal text-[10px]">{fgLabel}</span>
              </span>
            </div>
          )}
          {totalMcap != null && (
            <div className="flex justify-between">
              <span className="text-gray-400">Market Cap</span>
              <span className="text-white font-medium">${(totalMcap / 1e12).toFixed(2)}T</span>
            </div>
          )}
          {mcapChange != null && (
            <div className="flex justify-between">
              <span className="text-gray-400">24h Change</span>
              <span className={mcapChange >= 0 ? "text-green-400" : "text-red-400"}>
                {mcapChange >= 0 ? "+" : ""}{mcapChange.toFixed(2)}%
              </span>
            </div>
          )}
          {btcDom != null && (
            <div className="flex justify-between">
              <span className="text-gray-400">BTC Dom.</span>
              <span className="text-orange-400 font-medium">{btcDom.toFixed(1)}%</span>
            </div>
          )}
          {ethDom != null && (
            <div className="flex justify-between">
              <span className="text-gray-400">ETH Dom.</span>
              <span className="text-purple-400 font-medium">{ethDom.toFixed(1)}%</span>
            </div>
          )}
        </div>
      </div>
    </Html>
  );
}
