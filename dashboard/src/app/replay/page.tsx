"use client";

import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceDot,
} from "recharts";
import { getReplayData } from "@/lib/api";
import { cn, formatCurrency } from "@/lib/utils";
import { Play, Pause, RotateCcw, ChevronDown } from "lucide-react";
import type { ReplayEvent } from "@/types";

const SPEEDS = [1, 2, 5, 10, 50];
const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"];

interface CandlePoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface ReplaySignalMarker {
  time: string;
  action: "BUY" | "SELL" | "HOLD";
  confidence: number;
  price: number;
}

export default function ReplayPage() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [startDate, setStartDate] = useState("2025-02-01");
  const [endDate, setEndDate] = useState("2025-03-01");
  const [speed, setSpeed] = useState(5);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [allEvents, setAllEvents] = useState<ReplayEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const animRef = useRef<number>(0);
  const lastTickRef = useRef(0);

  // Separate candles, signals, trades from events
  const candles = useMemo(() => {
    return allEvents
      .filter((e) => e.type === "candle")
      .slice(0, currentIdx + 1)
      .map((e) => ({
        time: new Date(e.time).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit" }),
        open: e.open ?? 0,
        high: e.high ?? 0,
        low: e.low ?? 0,
        close: e.close ?? 0,
        volume: e.volume ?? 0,
      }));
  }, [allEvents, currentIdx]);

  const signalMarkers = useMemo(() => {
    return allEvents
      .filter((e) => e.type === "signal")
      .filter((_, i) => {
        const eventIndex = allEvents.findIndex((ae) => ae === allEvents.filter((e) => e.type === "signal")[i]);
        return eventIndex <= currentIdx;
      })
      .map((e) => ({
        time: e.time,
        action: e.action ?? "HOLD",
        confidence: e.confidence ?? 0,
        price: e.price ?? 0,
      }));
  }, [allEvents, currentIdx]);

  const visibleTrades = useMemo(() => {
    return allEvents
      .filter((e, i) => e.type === "trade" && i <= currentIdx);
  }, [allEvents, currentIdx]);

  const runningPnl = useMemo(() => {
    return visibleTrades.reduce((sum, t) => sum + (t.pnl ?? 0), 0);
  }, [visibleTrades]);

  const currentPrice = candles.length > 0 ? candles[candles.length - 1].close : 0;
  const totalCandles = allEvents.filter((e) => e.type === "candle").length;
  const progress = totalCandles > 0 ? (candles.length / totalCandles) * 100 : 0;
  const currentTime = currentIdx < allEvents.length ? allEvents[currentIdx].time : "";

  // Load data
  const handleLoad = useCallback(async () => {
    setLoading(true);
    setIsPlaying(false);
    setCurrentIdx(0);
    const data = await getReplayData(symbol, startDate, endDate);
    setAllEvents(data.events);
    setLoaded(true);
    setLoading(false);
  }, [symbol, startDate, endDate]);

  // Animation loop
  useEffect(() => {
    if (!isPlaying || allEvents.length === 0) return;

    const tick = (time: number) => {
      if (!lastTickRef.current) lastTickRef.current = time;
      const delta = time - lastTickRef.current;
      const interval = 1000 / speed;

      if (delta >= interval) {
        lastTickRef.current = time;
        setCurrentIdx((prev) => {
          if (prev >= allEvents.length - 1) {
            setIsPlaying(false);
            return prev;
          }
          return prev + 1;
        });
      }
      animRef.current = requestAnimationFrame(tick);
    };

    animRef.current = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(animRef.current);
      lastTickRef.current = 0;
    };
  }, [isPlaying, speed, allEvents.length]);

  const handleReset = () => {
    setIsPlaying(false);
    setCurrentIdx(0);
  };

  const handleProgressClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    setCurrentIdx(Math.floor(pct * (allEvents.length - 1)));
  };

  // Replay summary
  const isComplete = currentIdx >= allEvents.length - 1 && allEvents.length > 0;
  const totalTrades = visibleTrades.length;
  const winTrades = visibleTrades.filter((t) => (t.pnl ?? 0) > 0).length;
  const winRate = totalTrades > 0 ? (winTrades / totalTrades) * 100 : 0;
  const bestTrade = visibleTrades.length > 0 ? Math.max(...visibleTrades.map((t) => t.pnl ?? 0)) : 0;
  const worstTrade = visibleTrades.length > 0 ? Math.min(...visibleTrades.map((t) => t.pnl ?? 0)) : 0;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl sm:text-2xl font-bold text-white">Market Replay</h1>
        <p className="text-xs sm:text-sm text-gray-400">
          Watch the AI trade through historical periods
        </p>
      </div>

      {/* Controls */}
      <div className="card">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="text-[10px] text-gray-500 block mb-1">Symbol</label>
            <select
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white"
            >
              {SYMBOLS.map((s) => (
                <option key={s} value={s}>{s.replace("USDT", "/USDT")}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[10px] text-gray-500 block mb-1">Start</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white"
            />
          </div>
          <div>
            <label className="text-[10px] text-gray-500 block mb-1">End</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white"
            />
          </div>
          <div>
            <label className="text-[10px] text-gray-500 block mb-1">Speed</label>
            <div className="flex gap-1">
              {SPEEDS.map((s) => (
                <button
                  key={s}
                  onClick={() => setSpeed(s)}
                  className={cn(
                    "px-2 py-1.5 text-xs rounded",
                    speed === s
                      ? "bg-goblin-500/20 text-goblin-400 border border-goblin-500/30"
                      : "bg-gray-800 text-gray-400 border border-gray-700"
                  )}
                >
                  {s}x
                </button>
              ))}
            </div>
          </div>
          <button
            onClick={handleLoad}
            disabled={loading}
            className="btn-goblin px-4 py-1.5 text-sm"
          >
            {loading ? "Loading..." : "Load Data"}
          </button>
        </div>
      </div>

      {/* Player controls */}
      {loaded && (
        <div className="card">
          <div className="flex items-center gap-4 mb-3">
            <button
              onClick={() => setIsPlaying(!isPlaying)}
              className="h-10 w-10 rounded-full bg-goblin-500 flex items-center justify-center hover:bg-goblin-600 transition-colors"
            >
              {isPlaying ? <Pause size={18} className="text-white" /> : <Play size={18} className="text-white ml-0.5" />}
            </button>
            <button onClick={handleReset} className="text-gray-400 hover:text-white">
              <RotateCcw size={18} />
            </button>

            {/* Progress bar */}
            <div
              className="flex-1 h-2 rounded-full bg-gray-700 cursor-pointer"
              onClick={handleProgressClick}
            >
              <div
                className="h-2 rounded-full bg-goblin-500 transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>

            <span className="text-xs text-gray-400 font-mono whitespace-nowrap">
              {currentTime ? new Date(currentTime).toLocaleString() : "--"}
            </span>
          </div>

          {/* Running PnL */}
          <div className="flex items-center gap-4 text-sm">
            <span className="text-gray-500">Price:</span>
            <span className="font-bold text-white">{formatCurrency(currentPrice)}</span>
            <span className="text-gray-500 ml-4">P&L:</span>
            <span className={cn("font-bold", runningPnl >= 0 ? "text-profit" : "text-loss")}>
              {runningPnl >= 0 ? "+" : ""}{formatCurrency(runningPnl)}
            </span>
            <span className="text-gray-500 ml-4">Trades:</span>
            <span className="text-white">{totalTrades}</span>
          </div>
        </div>
      )}

      {/* Chart */}
      {loaded && candles.length > 0 && (
        <div className="card">
          <h3 className="section-title mb-3">Price Action</h3>
          <div className="h-[350px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={candles} margin={{ top: 5, right: 10, left: 10, bottom: 0 }}>
                <defs>
                  <linearGradient id="replayGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#22c55e" stopOpacity={0.15} />
                    <stop offset="100%" stopColor="#22c55e" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="time" tick={{ fontSize: 9, fill: "#6b7280" }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis domain={["auto", "auto"]} tick={{ fontSize: 10, fill: "#6b7280" }} axisLine={false} tickLine={false} width={70} tickFormatter={(v: number) => `$${v.toLocaleString()}`} />
                <Tooltip
                  contentStyle={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, fontSize: 11 }}
                  formatter={(v: number, name: string) => [`$${v.toLocaleString(undefined, { minimumFractionDigits: 2 })}`, name === "close" ? "Price" : name]}
                />
                <Area type="monotone" dataKey="close" stroke="#22c55e" fill="url(#replayGrad)" strokeWidth={2} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Signal feed */}
      {loaded && signalMarkers.length > 0 && (
        <div className="card">
          <h3 className="section-title mb-3">Signals During Replay</h3>
          <div className="max-h-[200px] overflow-y-auto space-y-1">
            {signalMarkers.slice(-10).reverse().map((s, i) => (
              <div key={i} className={cn(
                "flex items-center gap-3 px-3 py-1.5 rounded text-xs",
                s.action === "BUY" ? "bg-green-500/10" : s.action === "SELL" ? "bg-red-500/10" : "bg-gray-800/50"
              )}>
                <span className={cn(
                  "font-bold",
                  s.action === "BUY" ? "text-green-400" : s.action === "SELL" ? "text-red-400" : "text-gray-400"
                )}>{s.action}</span>
                <span className="text-gray-400">{(s.confidence * 100).toFixed(0)}%</span>
                <span className="text-gray-500 ml-auto font-mono">{new Date(s.time).toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Summary card */}
      {isComplete && (
        <div className="card border-goblin-500/30">
          <h3 className="section-title mb-3">Replay Summary</h3>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
            <div>
              <p className="text-xs text-gray-500">Total Return</p>
              <p className={cn("text-lg font-bold", runningPnl >= 0 ? "text-profit" : "text-loss")}>
                {runningPnl >= 0 ? "+" : ""}{formatCurrency(runningPnl)}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Trades</p>
              <p className="text-lg font-bold text-white">{totalTrades}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Win Rate</p>
              <p className="text-lg font-bold text-goblin-500">{winRate.toFixed(1)}%</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Best Trade</p>
              <p className="text-lg font-bold text-profit">{formatCurrency(bestTrade)}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Worst Trade</p>
              <p className="text-lg font-bold text-loss">{formatCurrency(worstTrade)}</p>
            </div>
          </div>
        </div>
      )}

      {!loaded && (
        <div className="card flex items-center justify-center py-20 text-gray-500">
          <p className="text-sm">Select a date range and click &quot;Load Data&quot; to start replay</p>
        </div>
      )}
    </div>
  );
}
