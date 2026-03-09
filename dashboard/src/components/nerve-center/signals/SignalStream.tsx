"use client";

import { useMemo } from "react";
import SignalPulse from "./SignalPulse";
import { fibonacciSphere } from "@/lib/nerve-center-utils";
import type { Signal } from "@/types";
import type { TickerPrice } from "@/lib/api";

interface SignalStreamProps {
  signals: Signal[];
  tickers: TickerPrice[];
  signalFilter: "ALL" | "BUY" | "SELL" | "HOLD";
}

export default function SignalStream({ signals, tickers, signalFilter }: SignalStreamProps) {
  const activePulses = useMemo(() => {
    const filtered = signalFilter === "ALL"
      ? signals
      : signals.filter((s) => s.action === signalFilter);

    return filtered.slice(0, 30).map((signal) => {
      const tickerIdx = tickers.findIndex((t) =>
        t.symbol.toUpperCase().includes(signal.symbol.replace("/", "").replace("USDT", "").toUpperCase())
      );

      let targetPos: [number, number, number];
      if (tickerIdx >= 0) {
        const isBTC = tickers[tickerIdx].symbol.toUpperCase().includes("BTC");
        if (isBTC) {
          targetPos = [0, 0, 0];
        } else {
          const [fx, , fz] = fibonacciSphere(tickerIdx, Math.max(tickers.length, 2), 12);
          targetPos = [fx, 0, fz];
        }
      } else {
        targetPos = [0, 0, 0];
      }

      return { signal, targetPos };
    });
  }, [signals, tickers, signalFilter]);

  return (
    <group>
      {activePulses.map(({ signal, targetPos }) => (
        <SignalPulse
          key={signal.signal_id}
          signal={signal}
          action={signal.action}
          confidence={signal.confidence}
          targetPosition={targetPos}
        />
      ))}
    </group>
  );
}
