"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useNerveCenterData } from "@/hooks/useNerveCenterData";
import DataPacket from "./DataPacket";
import { getZoneById } from "../zones/ZoneConfig";

/**
 * Zone position helpers — get the 3D world position (slightly elevated) for a zone.
 */
function zonePos(zoneId: string): [number, number, number] {
  const def = getZoneById(zoneId as any);
  if (!def) return [0, 2, 0];
  return [def.position[0], def.position[1] + 2, def.position[2]];
}

/**
 * Communication event — a real data change that triggers a visual packet.
 */
interface CommEvent {
  id: string;
  from: [number, number, number];
  to: [number, number, number];
  color: string;
  size: number;
  speed: number;
  arcHeight: number;
}

const MAX_ACTIVE = 10;

/**
 * CommunicationManager watches ALL live data from the trading system and
 * spawns beautiful animated data packets between zones when real events occur:
 *
 * - New signals → Oracle Tower → War Room / Treasury  (cyan/green/red)
 * - New trades → War Room → Treasury                   (gold)
 * - Price updates → Market Square → Oracle Tower        (blue)
 * - Model changes → Wizard Academy → Oracle Tower       (purple)
 * - Health changes → Guard Tower → affected zone        (red/green)
 * - Portfolio updates → Treasury → Guard Tower           (amber)
 */
export default function CommunicationManager() {
  const data = useNerveCenterData();
  const [activePackets, setActivePackets] = useState<CommEvent[]>([]);
  const initRef = useRef(false);

  // Previous state refs for change detection
  const prevSignalIds = useRef<Set<string>>(new Set());
  const prevTradeKeys = useRef<Set<string>>(new Set());
  const prevHealthMap = useRef<Map<string, string>>(new Map());
  const prevModelAccMap = useRef<Map<string, number>>(new Map());
  const prevTickerHash = useRef<string>("");
  const prevPortfolioValue = useRef<number>(0);

  const spawnPacket = useCallback((event: CommEvent) => {
    setActivePackets((prev) => [...prev, event].slice(-MAX_ACTIVE));
  }, []);

  const removePacket = useCallback((id: string) => {
    setActivePackets((prev) => prev.filter((p) => p.id !== id));
  }, []);

  // ── SIGNALS: Oracle Tower → War Room / Treasury ──
  useEffect(() => {
    if (!initRef.current) return;

    const newSignals = data.signals.filter((s) => !prevSignalIds.current.has(s.signal_id));
    prevSignalIds.current = new Set(data.signals.map((s) => s.signal_id));

    for (const sig of newSignals.slice(0, 3)) {
      const target = sig.action === "BUY" ? "warRoom" : sig.action === "SELL" ? "warRoom" : "treasury";
      const color = sig.action === "BUY" ? "#22c55e" : sig.action === "SELL" ? "#ef4444" : "#f59e0b";
      spawnPacket({
        id: `sig-${sig.signal_id}-${Date.now()}`,
        from: zonePos("oracleTower"),
        to: zonePos(target),
        color,
        size: 0.2 + sig.confidence * 0.15,
        speed: 0.5 + sig.confidence * 0.3,
        arcHeight: 6,
      });
    }
  }, [data.signals, spawnPacket]);

  // ── TRADES: War Room → Treasury ──
  useEffect(() => {
    if (!initRef.current) return;

    const newTrades = data.trades.filter((t) => {
      const key = `${t.symbol}-${t.closed_at}`;
      return !prevTradeKeys.current.has(key);
    });
    prevTradeKeys.current = new Set(data.trades.map((t) => `${t.symbol}-${t.closed_at}`));

    for (const trade of newTrades.slice(0, 2)) {
      const profit = trade.realized_pnl >= 0;
      spawnPacket({
        id: `trade-${trade.symbol}-${Date.now()}-${Math.random()}`,
        from: zonePos("warRoom"),
        to: zonePos("treasury"),
        color: profit ? "#fbbf24" : "#ef4444",
        size: profit ? 0.3 : 0.2,
        speed: 0.4,
        arcHeight: 7,
      });
    }
  }, [data.trades, spawnPacket]);

  // ── HEALTH: Guard Tower ↔ zones ──
  useEffect(() => {
    if (!initRef.current) return;

    for (const svc of data.health) {
      const prev = prevHealthMap.current.get(svc.service_name);
      if (prev && prev !== svc.status) {
        const isDown = svc.status === "down" || svc.status === "degraded";
        // Health event: Guard Tower sends alert
        spawnPacket({
          id: `health-${svc.service_name}-${Date.now()}`,
          from: isDown ? zonePos("guardTower") : zonePos("guardTower"),
          to: zonePos("treasury"),
          color: isDown ? "#ef4444" : "#22c55e",
          size: isDown ? 0.35 : 0.25,
          speed: isDown ? 0.7 : 0.5,
          arcHeight: 8,
        });
      }
      prevHealthMap.current.set(svc.service_name, svc.status);
    }
  }, [data.health, spawnPacket]);

  // ── MODELS: Wizard Academy → Oracle Tower ──
  useEffect(() => {
    if (!initRef.current) return;

    for (const model of data.models) {
      const prevAcc = prevModelAccMap.current.get(model.model_name);
      if (prevAcc !== undefined && Math.abs(prevAcc - model.accuracy) > 0.005) {
        const improved = model.accuracy > prevAcc;
        spawnPacket({
          id: `model-${model.model_name}-${Date.now()}`,
          from: zonePos("wizardAcademy"),
          to: zonePos("oracleTower"),
          color: improved ? "#a78bfa" : "#8b5cf6",
          size: 0.22,
          speed: 0.45,
          arcHeight: 5,
        });
      }
      prevModelAccMap.current.set(model.model_name, model.accuracy);
    }
  }, [data.models, spawnPacket]);

  // ── TICKERS: Market Square → Oracle Tower (on price changes) ──
  useEffect(() => {
    if (!initRef.current) return;

    // Hash ticker data to detect meaningful price changes
    const hash = data.tickers.slice(0, 5).map((t) => `${t.symbol}:${Number(t.lastPrice).toFixed(0)}`).join(",");
    if (hash !== prevTickerHash.current && prevTickerHash.current !== "") {
      // Find the biggest mover
      const maxChange = data.tickers.reduce((max, t) => {
        const pct = Math.abs(Number(t.priceChangePercent));
        return pct > max ? pct : max;
      }, 0);

      // Only spawn if there's notable movement
      if (maxChange > 0.5) {
        spawnPacket({
          id: `ticker-${Date.now()}`,
          from: zonePos("marketSquare"),
          to: zonePos("oracleTower"),
          color: "#3b82f6",
          size: 0.15 + Math.min(0.2, maxChange * 0.02),
          speed: 0.35,
          arcHeight: 4,
        });
      }
    }
    prevTickerHash.current = hash;
  }, [data.tickers, spawnPacket]);

  // ── PORTFOLIO: Treasury → Guard Tower (on value changes) ──
  useEffect(() => {
    if (!initRef.current) return;

    const currentValue = data.portfolio?.total_value ?? 0;
    if (prevPortfolioValue.current > 0 && Math.abs(currentValue - prevPortfolioValue.current) > 1) {
      spawnPacket({
        id: `portfolio-${Date.now()}`,
        from: zonePos("treasury"),
        to: zonePos("guardTower"),
        color: "#f59e0b",
        size: 0.18,
        speed: 0.4,
        arcHeight: 5,
      });
    }
    prevPortfolioValue.current = currentValue;
  }, [data.portfolio, spawnPacket]);

  // ── INIT: seed all refs on first render (avoid flooding) ──
  useEffect(() => {
    if (initRef.current) return;

    prevSignalIds.current = new Set(data.signals.map((s) => s.signal_id));
    prevTradeKeys.current = new Set(data.trades.map((t) => `${t.symbol}-${t.closed_at}`));
    for (const svc of data.health) prevHealthMap.current.set(svc.service_name, svc.status);
    for (const model of data.models) prevModelAccMap.current.set(model.model_name, model.accuracy);
    prevTickerHash.current = data.tickers.slice(0, 5).map((t) => `${t.symbol}:${Number(t.lastPrice).toFixed(0)}`).join(",");
    prevPortfolioValue.current = data.portfolio?.total_value ?? 0;

    // Mark as initialized only after we've loaded some data
    if (data.signals.length > 0 || data.health.length > 0 || data.tickers.length > 0) {
      initRef.current = true;
    }
  }, [data]);

  return (
    <group>
      {activePackets.map((packet) => (
        <DataPacket
          key={packet.id}
          from={packet.from}
          to={packet.to}
          color={packet.color}
          size={packet.size}
          speed={packet.speed}
          arcHeight={packet.arcHeight}
          onComplete={() => removePacket(packet.id)}
        />
      ))}
    </group>
  );
}
