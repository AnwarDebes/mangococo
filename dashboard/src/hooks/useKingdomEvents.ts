"use client";

import { useEffect, useRef } from "react";
import { useNerveCenterStore } from "@/components/nerve-center/NerveCenterStore";
import { useNerveCenterData } from "./useNerveCenterData";

/** Watches real-time data changes and generates RPG-flavored kingdom events. */
export function useKingdomEvents() {
  const data = useNerveCenterData();
  const addEvent = useNerveCenterStore((s) => s.addEvent);

  const prevSignals = useRef<Set<string>>(new Set());
  const prevTrades = useRef<Set<string>>(new Set());
  const prevHealth = useRef<Map<string, string>>(new Map());
  const initRef = useRef(false);

  // New signals
  useEffect(() => {
    if (!initRef.current) {
      // First render — seed refs without generating events
      prevSignals.current = new Set(data.signals.map((s) => s.signal_id));
      prevTrades.current = new Set(data.trades.map((t) => `${t.symbol}-${t.closed_at}`));
      for (const svc of data.health) {
        prevHealth.current.set(svc.service_name, svc.status);
      }
      initRef.current = true;
      return;
    }

    // Detect new signals
    for (const sig of data.signals) {
      if (!prevSignals.current.has(sig.signal_id)) {
        const conf = Math.round(sig.confidence * 100);
        const sym = sig.symbol.replace("/USDT", "");
        addEvent({
          id: `sig-${sig.signal_id}`,
          timestamp: Date.now(),
          type: "signal",
          message: `The Oracle detected a ${sig.action} quest for ${sym} (${conf}% power)`,
          icon: sig.action === "BUY" ? "🟢" : sig.action === "SELL" ? "🔴" : "🟡",
          color: sig.action === "BUY" ? "#22c55e" : sig.action === "SELL" ? "#ef4444" : "#f59e0b",
        });
      }
    }
    prevSignals.current = new Set(data.signals.map((s) => s.signal_id));
  }, [data.signals, addEvent]);

  // Health changes
  useEffect(() => {
    if (!initRef.current) return;

    for (const svc of data.health) {
      const prev = prevHealth.current.get(svc.service_name);
      if (prev && prev !== svc.status) {
        const name = svc.service_name.replace(/_/g, " ");
        if (svc.status === "down") {
          addEvent({
            id: `health-${svc.service_name}-${Date.now()}`,
            timestamp: Date.now(),
            type: "health",
            message: `${name} goblin has fallen! Sending healers...`,
            icon: "💀",
            color: "#ef4444",
          });
        } else if (svc.status === "healthy" && prev !== "healthy") {
          addEvent({
            id: `health-${svc.service_name}-${Date.now()}`,
            timestamp: Date.now(),
            type: "health",
            message: `${name} goblin has been healed and returns to duty!`,
            icon: "💚",
            color: "#22c55e",
          });
        } else if (svc.status === "degraded") {
          addEvent({
            id: `health-${svc.service_name}-${Date.now()}`,
            timestamp: Date.now(),
            type: "health",
            message: `${name} goblin is feeling weak...`,
            icon: "⚠️",
            color: "#f59e0b",
          });
        }
      }
      prevHealth.current.set(svc.service_name, svc.status);
    }
  }, [data.health, addEvent]);

  // New trades
  useEffect(() => {
    if (!initRef.current) return;

    for (const trade of data.trades) {
      const key = `${trade.symbol}-${trade.closed_at}`;
      if (!prevTrades.current.has(key)) {
        const sym = trade.symbol.replace("/USDT", "");
        const profit = trade.realized_pnl >= 0;
        addEvent({
          id: `trade-${key}`,
          timestamp: Date.now(),
          type: "trade",
          message: profit
            ? `Merchant won a ${trade.side} battle on ${sym}! +$${trade.realized_pnl.toFixed(2)}`
            : `Merchant lost a ${trade.side} battle on ${sym}. -$${Math.abs(trade.realized_pnl).toFixed(2)}`,
          icon: profit ? "⚔️" : "💔",
          color: profit ? "#22c55e" : "#ef4444",
        });
      }
    }
    prevTrades.current = new Set(data.trades.map((t) => `${t.symbol}-${t.closed_at}`));
  }, [data.trades, addEvent]);
}
