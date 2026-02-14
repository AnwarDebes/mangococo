"use client";

import { useMemo } from "react";
import { formatPrice } from "@/lib/utils";

interface LiveOrderBookProps {
  bids: Array<[number, number]>; // [price, volume]
  asks: Array<[number, number]>; // [price, volume]
  symbol: string;
}

export default function LiveOrderBook({ bids, asks, symbol }: LiveOrderBookProps) {
  const {
    displayBids,
    displayAsks,
    maxVolume,
    midPrice,
    imbalance,
    totalBidVol,
    totalAskVol,
  } = useMemo(() => {
    const topBids = bids.slice(0, 15);
    const topAsks = asks.slice(0, 15);

    const allVolumes = [...topBids, ...topAsks].map((l) => l[1]);
    const maxVol = Math.max(...allVolumes, 1);
    const bestBid = topBids.length > 0 ? topBids[0][0] : 0;
    const bestAsk = topAsks.length > 0 ? topAsks[0][0] : 0;
    const mid = (bestBid + bestAsk) / 2;

    const bidVolTotal = topBids.reduce((s, l) => s + l[1], 0);
    const askVolTotal = topAsks.reduce((s, l) => s + l[1], 0);
    const totalVol = bidVolTotal + askVolTotal;
    const imb = totalVol > 0 ? ((bidVolTotal - askVolTotal) / totalVol) * 100 : 0;

    // Compute cumulative volumes for depth fill
    let cumBid = 0;
    const dBids = topBids.map(([price, vol]) => {
      cumBid += vol;
      return { price, volume: vol, cumulative: cumBid };
    });

    let cumAsk = 0;
    const dAsks = topAsks.map(([price, vol]) => {
      cumAsk += vol;
      return { price, volume: vol, cumulative: cumAsk };
    });

    return {
      displayBids: dBids,
      displayAsks: dAsks,
      maxVolume: maxVol,
      midPrice: mid,
      imbalance: imb,
      totalBidVol: bidVolTotal,
      totalAskVol: askVolTotal,
    };
  }, [bids, asks]);
  const maxCumulative = Math.max(
    displayBids.length > 0 ? displayBids[displayBids.length - 1].cumulative : 0,
    displayAsks.length > 0 ? displayAsks[displayAsks.length - 1].cumulative : 0,
    1
  );

  return (
    <div className="w-full max-w-[300px] rounded-lg border border-gray-800 bg-gray-900 p-3">
      {/* Header */}
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold text-gray-400">{symbol} Order Book</h3>
        <span
          className={`text-[10px] font-medium ${
            imbalance > 0 ? "text-profit" : imbalance < 0 ? "text-loss" : "text-gray-500"
          }`}
        >
          Imb: {imbalance >= 0 ? "+" : ""}{imbalance.toFixed(1)}%
        </span>
      </div>

      {/* Column headers */}
      <div className="mb-1 grid grid-cols-2 gap-1 text-[10px] text-gray-600">
        <div className="flex justify-between px-1">
          <span>Vol</span>
          <span>Bid</span>
        </div>
        <div className="flex justify-between px-1">
          <span>Ask</span>
          <span>Vol</span>
        </div>
      </div>
      {/* Order book rows */}
      <div className="space-y-px">
        {Array.from({ length: 15 }).map((_, i) => {
          const bid = displayBids[i];
          const ask = displayAsks[i];
          const bidBarWidth = bid ? (bid.volume / maxVolume) * 100 : 0;
          const askBarWidth = ask ? (ask.volume / maxVolume) * 100 : 0;
          const bidDepthWidth = bid ? (bid.cumulative / maxCumulative) * 100 : 0;
          const askDepthWidth = ask ? (ask.cumulative / maxCumulative) * 100 : 0;

          return (
            <div key={i} className="grid grid-cols-2 gap-1">
              {/* Bid side */}
              <div className="relative flex h-5 items-center justify-between overflow-hidden rounded-sm px-1">
                {/* Cumulative depth fill */}
                <div
                  className="absolute inset-y-0 right-0 bg-green-900/20"
                  style={{ width: `${bidDepthWidth}%` }}
                />
                {/* Volume bar */}
                <div
                  className="absolute inset-y-0 right-0 bg-green-600/30"
                  style={{ width: `${bidBarWidth}%` }}
                />
                <span className="relative z-10 text-[10px] text-gray-500 font-mono">
                  {bid ? bid.volume.toFixed(2) : ""}
                </span>
                <span className="relative z-10 text-[10px] text-profit font-mono font-medium">
                  {bid ? formatPrice(bid.price) : ""}
                </span>
              </div>
              {/* Ask side */}
              <div className="relative flex h-5 items-center justify-between overflow-hidden rounded-sm px-1">
                <div
                  className="absolute inset-y-0 left-0 bg-red-900/20"
                  style={{ width: `${askDepthWidth}%` }}
                />
                <div
                  className="absolute inset-y-0 left-0 bg-red-600/30"
                  style={{ width: `${askBarWidth}%` }}
                />
                <span className="relative z-10 text-[10px] text-loss font-mono font-medium">
                  {ask ? formatPrice(ask.price) : ""}
                </span>
                <span className="relative z-10 text-[10px] text-gray-500 font-mono">
                  {ask ? ask.volume.toFixed(2) : ""}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Mid price */}
      <div className="mt-2 flex items-center justify-center gap-2 border-t border-gray-800 pt-2">
        <span className="text-xs text-gray-500">Mid</span>
        <span className="text-sm font-bold text-mango-400 font-mono">
          ${formatPrice(midPrice)}
        </span>
      </div>
    </div>
  );
}