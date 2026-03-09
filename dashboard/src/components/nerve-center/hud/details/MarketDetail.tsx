"use client";

import { useMemo } from "react";
import type { FearGreedData, GlobalMarketData } from "@/types";
import type { TickerPrice } from "@/lib/api";

interface Props {
  tickers: TickerPrice[];
  fearGreed?: FearGreedData;
  globalMarket?: GlobalMarketData;
}

export default function MarketDetail({ tickers, fearGreed, globalMarket }: Props) {
  const fgValue = Number(fearGreed?.data?.[0]?.value ?? 50);
  const fgLabel = fearGreed?.data?.[0]?.value_classification ?? "Neutral";
  const marketCap = globalMarket?.data?.total_market_cap?.usd;
  const marketChange = globalMarket?.data?.market_cap_change_percentage_24h_usd;
  const btcDom = globalMarket?.data?.market_cap_percentage?.btc;
  const ethDom = globalMarket?.data?.market_cap_percentage?.eth;

  const fgColor = fgValue <= 25 ? "#ef4444" : fgValue <= 45 ? "#f59e0b" : fgValue <= 55 ? "#8b5cf6" : "#22c55e";

  const sortedTickers = useMemo(() => {
    return [...tickers].sort((a, b) =>
      Math.abs(Number(b.priceChangePercent)) - Math.abs(Number(a.priceChangePercent))
    );
  }, [tickers]);

  return (
    <div className="space-y-3">
      {/* Fear & Greed */}
      <div className="text-center bg-gray-900/50 rounded-lg px-3 py-3">
        <div className="text-[9px] text-blue-400 uppercase font-bold">World Mood</div>
        {/* Semi-circle gauge */}
        <div className="relative mx-auto w-28 h-14 mt-1">
          <svg viewBox="0 0 100 50" className="w-full h-full">
            <path d="M5,50 A45,45 0 0,1 95,50" fill="none" stroke="#1f2937" strokeWidth={8} strokeLinecap="round" />
            <path
              d="M5,50 A45,45 0 0,1 95,50"
              fill="none"
              stroke={fgColor}
              strokeWidth={8}
              strokeLinecap="round"
              strokeDasharray={`${(fgValue / 100) * 141.37} 141.37`}
            />
          </svg>
          <div className="absolute bottom-0 left-1/2 -translate-x-1/2 text-center">
            <div className="text-xl font-black" style={{ color: fgColor }}>{fgValue}</div>
          </div>
        </div>
        <div className="text-xs font-bold mt-1" style={{ color: fgColor }}>{fgLabel}</div>
      </div>

      {/* Market stats */}
      <div className="grid grid-cols-2 gap-1.5">
        {marketCap != null && (
          <div className="bg-gray-900/50 rounded-lg px-2 py-1.5 text-center">
            <div className="text-[9px] text-gray-500">Market Cap</div>
            <div className="text-sm font-bold text-white">${(marketCap / 1e12).toFixed(2)}T</div>
          </div>
        )}
        {marketChange != null && (
          <div className="bg-gray-900/50 rounded-lg px-2 py-1.5 text-center">
            <div className="text-[9px] text-gray-500">24h Change</div>
            <div className={`text-sm font-bold ${marketChange >= 0 ? "text-green-400" : "text-red-400"}`}>
              {marketChange >= 0 ? "+" : ""}{marketChange.toFixed(2)}%
            </div>
          </div>
        )}
        {btcDom != null && (
          <div className="bg-gray-900/50 rounded-lg px-2 py-1.5 text-center">
            <div className="text-[9px] text-gray-500">BTC Dom</div>
            <div className="text-sm font-bold text-orange-300">{btcDom.toFixed(1)}%</div>
          </div>
        )}
        {ethDom != null && (
          <div className="bg-gray-900/50 rounded-lg px-2 py-1.5 text-center">
            <div className="text-[9px] text-gray-500">ETH Dom</div>
            <div className="text-sm font-bold text-blue-300">{ethDom.toFixed(1)}%</div>
          </div>
        )}
      </div>

      {/* Top movers */}
      <div>
        <div className="text-[9px] text-gray-500 uppercase font-bold mb-1">Top Movers</div>
        <div className="space-y-1">
          {sortedTickers.slice(0, 8).map((t) => {
            const pct = Number(t.priceChangePercent);
            const up = pct >= 0;
            return (
              <div key={t.symbol} className="flex items-center justify-between bg-gray-900/50 rounded px-2 py-1 border border-gray-800/50">
                <span className="text-[10px] font-bold text-white">{t.symbol.replace("USDT", "")}</span>
                <span className="text-[10px] text-gray-400">
                  ${Number(t.lastPrice).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </span>
                <span className={`text-[10px] font-bold ${up ? "text-green-400" : "text-red-400"}`}>
                  {up ? "▲" : "▼"} {Math.abs(pct).toFixed(1)}%
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
