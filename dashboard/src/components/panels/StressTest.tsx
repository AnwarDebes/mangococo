"use client";

import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { runStressTest } from "@/lib/api";
import { cn, formatCurrency } from "@/lib/utils";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { StressResult, StressScenario } from "@/types";

const PRESETS: StressScenario[] = [
  { name: "2022 Luna Crash", crash_pct: -60, duration_days: 3 },
  { name: "2020 COVID Dump", crash_pct: -40, duration_days: 1 },
  { name: "Mild Correction", crash_pct: -15, duration_days: 14 },
  { name: "Stablecoin Depeg", crash_pct: -5, duration_days: 2 },
  { name: "Black Swan", crash_pct: -80, duration_days: 30 },
];

function MonteCarloChart({ volatility, currentPrice }: { volatility: number; currentPrice: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !currentPrice) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    const paths = 100;
    const steps = 60;
    const vol = volatility || 0.02;
    const allPrices: number[][] = [];

    // Generate all paths
    for (let p = 0; p < paths; p++) {
      const prices = [currentPrice];
      for (let s = 1; s < steps; s++) {
        const ret = (Math.random() - 0.5) * vol * 2;
        prices.push(prices[s - 1] * (1 + ret));
      }
      allPrices.push(prices);
    }

    // Find min/max for scaling
    let minP = Infinity, maxP = -Infinity;
    for (const prices of allPrices) {
      for (const p of prices) {
        if (p < minP) minP = p;
        if (p > maxP) maxP = p;
      }
    }
    const range = maxP - minP || 1;

    const toX = (i: number) => (i / (steps - 1)) * w;
    const toY = (p: number) => h - ((p - minP) / range) * (h - 10) - 5;

    // Draw paths
    for (const prices of allPrices) {
      ctx.beginPath();
      ctx.moveTo(toX(0), toY(prices[0]));
      for (let s = 1; s < steps; s++) {
        ctx.lineTo(toX(s), toY(prices[s]));
      }
      ctx.strokeStyle = "rgba(34,197,94,0.08)";
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    // Draw 5th and 95th percentile
    for (let s = 0; s < steps; s++) {
      const vals = allPrices.map((p) => p[s]).sort((a, b) => a - b);
      const p5 = vals[Math.floor(paths * 0.05)];
      const p95 = vals[Math.floor(paths * 0.95)];
      const median = vals[Math.floor(paths * 0.5)];

      if (s > 0) {
        const prevVals = allPrices.map((p) => p[s - 1]).sort((a, b) => a - b);
        const prevP5 = prevVals[Math.floor(paths * 0.05)];
        const prevP95 = prevVals[Math.floor(paths * 0.95)];
        const prevMed = prevVals[Math.floor(paths * 0.5)];

        ctx.beginPath();
        ctx.moveTo(toX(s - 1), toY(prevP5));
        ctx.lineTo(toX(s), toY(p5));
        ctx.strokeStyle = "rgba(239,68,68,0.5)";
        ctx.lineWidth = 1.5;
        ctx.stroke();

        ctx.beginPath();
        ctx.moveTo(toX(s - 1), toY(prevP95));
        ctx.lineTo(toX(s), toY(p95));
        ctx.strokeStyle = "rgba(34,197,94,0.5)";
        ctx.lineWidth = 1.5;
        ctx.stroke();

        ctx.beginPath();
        ctx.moveTo(toX(s - 1), toY(prevMed));
        ctx.lineTo(toX(s), toY(median));
        ctx.strokeStyle = "rgba(255,255,255,0.4)";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    }
  }, [volatility, currentPrice]);

  return (
    <div>
      <p className="text-xs text-gray-500 mb-2">Monte Carlo Simulation (100 paths)</p>
      <canvas
        ref={canvasRef}
        width={600}
        height={200}
        className="w-full h-[200px] rounded-lg bg-gray-950/50"
      />
      <div className="flex justify-between text-[9px] text-gray-600 mt-1 px-1">
        <span>Now</span>
        <span>+30 days</span>
      </div>
    </div>
  );
}

export default function StressTest() {
  const [selectedScenario, setSelectedScenario] = useState<StressScenario | null>(null);
  const [customCrash, setCustomCrash] = useState(-30);
  const [customDays, setCustomDays] = useState(7);
  const [result, setResult] = useState<StressResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [showCustom, setShowCustom] = useState(false);

  const handleScenario = useCallback(async (scenario: StressScenario) => {
    setSelectedScenario(scenario);
    setLoading(true);
    const res = await runStressTest(scenario);
    setResult(res);
    setLoading(false);
  }, []);

  const handleCustom = useCallback(async () => {
    const scenario: StressScenario = {
      name: `Custom (${customCrash}% / ${customDays}d)`,
      crash_pct: customCrash,
      duration_days: customDays,
    };
    await handleScenario(scenario);
  }, [customCrash, customDays, handleScenario]);

  return (
    <div className="card">
      <h3 className="section-title mb-3">Portfolio Stress Tester</h3>

      {/* Scenario buttons */}
      <div className="flex flex-wrap gap-2 mb-4">
        {PRESETS.map((p) => (
          <button
            key={p.name}
            onClick={() => handleScenario(p)}
            className={cn(
              "px-3 py-1.5 text-xs rounded-lg border transition-colors",
              selectedScenario?.name === p.name
                ? "border-goblin-500/50 bg-goblin-500/10 text-goblin-400"
                : "border-gray-700 bg-gray-800 text-gray-400 hover:text-white hover:border-gray-600"
            )}
          >
            {p.name}
          </button>
        ))}
        <button
          onClick={() => setShowCustom(!showCustom)}
          className={cn(
            "px-3 py-1.5 text-xs rounded-lg border transition-colors",
            showCustom
              ? "border-gold-500/50 bg-gold-500/10 text-gold-400"
              : "border-gray-700 bg-gray-800 text-gray-400 hover:text-white"
          )}
        >
          Custom
        </button>
      </div>

      {/* Custom controls */}
      {showCustom && (
        <div className="flex flex-wrap items-end gap-3 mb-4 p-3 rounded-lg bg-gray-900/50 border border-gray-800">
          <div>
            <label className="text-[10px] text-gray-500 block mb-1">Crash %</label>
            <input
              type="range"
              min={-90}
              max={-5}
              value={customCrash}
              onChange={(e) => setCustomCrash(Number(e.target.value))}
              className="w-32 accent-red-500"
            />
            <span className="text-xs text-red-400 ml-2">{customCrash}%</span>
          </div>
          <div>
            <label className="text-[10px] text-gray-500 block mb-1">Duration (days)</label>
            <input
              type="number"
              min={1}
              max={30}
              value={customDays}
              onChange={(e) => setCustomDays(Number(e.target.value))}
              className="w-16 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white"
            />
          </div>
          <button onClick={handleCustom} className="btn-goblin px-3 py-1 text-xs">
            Run
          </button>
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-10 text-sm text-gray-500">
          Running stress test...
        </div>
      )}

      {/* Results */}
      {result && !loading && (
        <div className="space-y-4">
          {/* Impact headline */}
          <div className="text-center py-2">
            <p className="text-sm text-gray-400">Your portfolio would lose</p>
            <p className="text-3xl font-bold text-red-400">
              {formatCurrency(result.total_loss)} ({result.total_loss_pct.toFixed(1)}%)
            </p>
            {result.stop_loss_savings > 0 && (
              <p className="text-xs text-green-400 mt-1">
                Stop-losses would save {formatCurrency(result.stop_loss_savings)}
              </p>
            )}
          </div>

          {/* Before/After bars */}
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <p className="text-[10px] text-gray-500 mb-1">Current</p>
              <div className="h-6 rounded bg-goblin-500/30 flex items-center px-2">
                <span className="text-xs font-bold text-goblin-400">{formatCurrency(result.original_value)}</span>
              </div>
            </div>
            <div className="text-gray-600">→</div>
            <div className="flex-1">
              <p className="text-[10px] text-gray-500 mb-1">After {selectedScenario?.name}</p>
              <div className="h-6 rounded bg-red-500/20 flex items-center px-2"
                style={{ width: `${Math.max(20, (result.stressed_value / result.original_value) * 100)}%` }}>
                <span className="text-xs font-bold text-red-400">{formatCurrency(result.stressed_value)}</span>
              </div>
            </div>
          </div>

          {/* Per-position waterfall */}
          {result.per_position.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 mb-2">Per-Position Impact</p>
              <div className="h-[150px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={result.per_position} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
                    <XAxis
                      dataKey="symbol"
                      tick={{ fontSize: 9, fill: "#6b7280" }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      tick={{ fontSize: 9, fill: "#6b7280" }}
                      axisLine={false}
                      tickLine={false}
                      tickFormatter={(v: number) => `$${v.toFixed(2)}`}
                    />
                    <Tooltip
                      contentStyle={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, fontSize: 11 }}
                      formatter={(v: number) => [formatCurrency(Math.abs(v)), "Loss"]}
                    />
                    <Bar dataKey="loss" radius={[4, 4, 0, 0]}>
                      {result.per_position.map((p, i) => (
                        <Cell key={i} fill={p.stop_loss_triggered ? "#f59e0b" : "#ef4444"} opacity={0.7} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
            <div>
              <p className="text-[10px] text-gray-500">Positions Liquidated</p>
              <p className="text-sm font-bold text-red-400">{result.positions_liquidated}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500">Positions Survived</p>
              <p className="text-sm font-bold text-green-400">{result.positions_survived}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500">Cash Remaining</p>
              <p className="text-sm font-bold text-white">{formatCurrency(result.cash_remaining)}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500">Est. Recovery</p>
              <p className="text-sm font-bold text-gold-500">{result.recovery_days}d</p>
            </div>
          </div>

          {/* Monte Carlo */}
          <MonteCarloChart
            volatility={Math.abs((selectedScenario?.crash_pct ?? 30) / 100) * 0.15}
            currentPrice={result.original_value}
          />
        </div>
      )}

      {!result && !loading && (
        <p className="text-sm text-gray-600 text-center py-6">
          Select a scenario to stress test your portfolio
        </p>
      )}
    </div>
  );
}
