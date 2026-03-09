"use client";

import { Html } from "@react-three/drei";
import { useNerveCenterStore } from "../NerveCenterStore";
import type { TickerPrice } from "@/lib/api";
import type { SentimentData, Signal } from "@/types";

interface CryptoDetailPanelProps {
  ticker: TickerPrice;
  sentiment?: SentimentData;
  signal?: Signal;
  position: [number, number, number];
}

export default function CryptoDetailPanel({ ticker, sentiment, signal, position }: CryptoDetailPanelProps) {
  const selectNode = useNerveCenterStore((s) => s.selectNode);
  const change = parseFloat(ticker.priceChangePercent || "0");
  const price = parseFloat(ticker.lastPrice || "0");

  return (
    <group position={position}>
      <Html distanceFactor={10} style={{ pointerEvents: "auto" }}>
        <div className="bg-gray-900/95 border border-goblin-500/30 rounded-lg p-4 w-72 backdrop-blur text-white">
          <div className="flex justify-between items-center mb-3">
            <span className="text-lg font-bold">{ticker.symbol.replace("USDT", "")}/USDT</span>
            <button
              onClick={() => selectNode(null)}
              className="text-gray-400 hover:text-white text-sm px-1"
            >
              X
            </button>
          </div>

          <div className="text-2xl font-bold mb-1">${price.toLocaleString()}</div>
          <div className={`text-sm font-medium mb-3 ${change >= 0 ? "text-green-400" : "text-red-400"}`}>
            {change >= 0 ? "+" : ""}{change.toFixed(2)}% (24h)
          </div>

          {/* Volume */}
          {ticker.volume && parseFloat(ticker.volume) > 0 && (
            <div className="text-xs text-gray-400 mb-3">
              Volume: ${Number(parseFloat(ticker.volume).toFixed(0)).toLocaleString()}
            </div>
          )}

          {/* Sentiment */}
          {sentiment && (
            <div className="mb-3 border-t border-gray-700 pt-2">
              <div className="text-xs text-gray-400 mb-1">Sentiment Score</div>
              <div className="w-full bg-gray-800 rounded-full h-2 mb-1">
                <div
                  className="h-2 rounded-full transition-all"
                  style={{
                    width: `${sentiment.score}%`,
                    backgroundColor: sentiment.score > 60 ? "#22c55e" : sentiment.score < 40 ? "#ef4444" : "#f59e0b",
                  }}
                />
              </div>
              <div className="flex justify-between text-[10px] text-gray-500">
                <span>{sentiment.score.toFixed(0)}/100</span>
                <span>Fear/Greed: {sentiment.fear_greed_index}</span>
              </div>
              <div className="flex gap-3 mt-1.5 text-xs">
                <div>
                  <span className="text-gray-500">1h: </span>
                  <span className={sentiment.momentum_1h >= 0 ? "text-green-400" : "text-red-400"}>
                    {sentiment.momentum_1h >= 0 ? "▲" : "▼"} {Math.abs(sentiment.momentum_1h).toFixed(1)}
                  </span>
                </div>
                <div>
                  <span className="text-gray-500">24h: </span>
                  <span className={sentiment.momentum_24h >= 0 ? "text-green-400" : "text-red-400"}>
                    {sentiment.momentum_24h >= 0 ? "▲" : "▼"} {Math.abs(sentiment.momentum_24h).toFixed(1)}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Latest signal */}
          {signal && (
            <div className="border-t border-gray-700 pt-2">
              <div className="text-xs text-gray-400 mb-1">Latest Signal</div>
              <div className="flex items-center gap-2">
                <span
                  className={`px-2 py-0.5 rounded text-xs font-bold ${
                    signal.action === "BUY" ? "bg-green-500/20 text-green-400" :
                    signal.action === "SELL" ? "bg-red-500/20 text-red-400" :
                    "bg-yellow-500/20 text-yellow-400"
                  }`}
                >
                  {signal.action}
                </span>
                <span className="text-xs text-gray-300">
                  {(signal.confidence * 100).toFixed(0)}% confidence
                </span>
              </div>
              <div className="text-[10px] text-gray-500 mt-1">
                {new Date(signal.timestamp).toLocaleString()}
              </div>
            </div>
          )}
        </div>
      </Html>
    </group>
  );
}
