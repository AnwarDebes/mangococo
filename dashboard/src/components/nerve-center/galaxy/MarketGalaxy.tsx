"use client";

import { useMemo } from "react";
import CryptoNode from "./CryptoNode";
import OrbitalRings from "./OrbitalRings";
import { fibonacciSphere } from "@/lib/nerve-center-utils";
import type { TickerPrice } from "@/lib/api";
import type { SentimentData, Signal } from "@/types";

interface MarketGalaxyProps {
  tickers: TickerPrice[];
  sentiment: SentimentData[];
  signals: Signal[];
}

export default function MarketGalaxy({ tickers, sentiment, signals }: MarketGalaxyProps) {
  const nodeData = useMemo(() => {
    if (!tickers.length) return [];

    return tickers.map((ticker, i) => {
      const sentimentData = sentiment.find(
        (s) => ticker.symbol.toUpperCase().includes(s.symbol.replace("/", "").toUpperCase())
      );
      const latestSignal = signals.find(
        (s) => ticker.symbol.toUpperCase().includes(s.symbol.replace("/", "").toUpperCase())
      );

      // BTC at center, others on fibonacci sphere
      const isBTC = ticker.symbol.toUpperCase().includes("BTC");
      const sentimentY = sentimentData ? ((sentimentData.score - 50) / 50) * 3 : 0;

      let pos: [number, number, number];
      if (isBTC) {
        pos = [0, 0, 0];
      } else {
        const [fx, , fz] = fibonacciSphere(i, Math.max(tickers.length, 2), 12);
        pos = [fx, sentimentY, fz];
      }

      return { ticker, position: pos, sentiment: sentimentData, signal: latestSignal, index: i };
    });
  }, [tickers, sentiment, signals]);

  return (
    <group>
      <OrbitalRings />
      {nodeData.map((nd) => (
        <CryptoNode
          key={nd.ticker.symbol}
          ticker={nd.ticker}
          position={nd.position}
          sentiment={nd.sentiment}
          signal={nd.signal}
          index={nd.index}
        />
      ))}
    </group>
  );
}
