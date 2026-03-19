"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  Radar,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { getSignalExplanation } from "@/lib/api";
import type { SignalExplanation } from "@/types";
import { cn } from "@/lib/utils";

interface Props {
  signalId: string;
  symbol: string;
  onClose: () => void;
}

function ConfidenceArc({ value, size = 80 }: { value: number; size?: number }) {
  const r = (size - 8) / 2;
  const c = 2 * Math.PI * r;
  const offset = c - (value * c);
  return (
    <svg width={size} height={size} className="-rotate-90">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#1f2937" strokeWidth={4} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#22c55e" strokeWidth={4}
        strokeDasharray={c} strokeDashoffset={offset} strokeLinecap="round" className="transition-all duration-700" />
    </svg>
  );
}

function RiskGauge({ score }: { score: number }) {
  const pct = Math.min(100, Math.max(0, score));
  const color = pct < 33 ? "#22c55e" : pct < 66 ? "#f59e0b" : "#ef4444";
  return (
    <div className="flex flex-col items-center">
      <div className="relative h-12 w-24">
        <svg viewBox="0 0 100 50" className="w-full">
          <path d="M 5 50 A 45 45 0 0 1 95 50" fill="none" stroke="#1f2937" strokeWidth={8} strokeLinecap="round" />
          <path d="M 5 50 A 45 45 0 0 1 95 50" fill="none" stroke={color} strokeWidth={8} strokeLinecap="round"
            strokeDasharray={`${pct * 1.41} 141`} className="transition-all duration-700" />
        </svg>
        <span className="absolute inset-x-0 bottom-0 text-center text-sm font-bold text-white">{score}</span>
      </div>
      <span className="text-[10px] text-gray-500 mt-1">Risk Score</span>
    </div>
  );
}

export default function SignalExplainer({ signalId, symbol, onClose }: Props) {
  const [data, setData] = useState<SignalExplanation | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getSignalExplanation(signalId, symbol).then((d) => {
      setData(d);
      setLoading(false);
    });
  }, [signalId, symbol]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (loading || !data) {
    return (
      <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
        <div className="card skeleton-shimmer w-96 h-48" />
      </div>
    );
  }

  const isPartial = data.data_quality === "partial";

  const radarData = [
    { axis: "RSI", value: data.market_snapshot.rsi ?? 50 },
    { axis: "Volume", value: Math.min(100, (data.market_snapshot.volume_vs_avg ?? 1) * 40) },
    { axis: "Trend", value: data.market_snapshot.trend === "uptrend" ? 80 : data.market_snapshot.trend === "downtrend" ? 20 : 50 },
    { axis: "Volatility", value: data.market_snapshot.volatility === "high" ? 90 : data.market_snapshot.volatility === "medium" ? 50 : 20 },
    { axis: "Sentiment", value: 50 + (data.top_factors.find((f) => f.feature.includes("sentiment"))?.impact || 0) * 50 },
  ];

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" onClick={onClose}>
      <div className="relative w-full max-w-[900px] max-h-[90vh] overflow-y-auto rounded-2xl border border-gray-700 bg-gray-900/95 backdrop-blur-xl shadow-2xl"
        onClick={(e) => e.stopPropagation()}>
        {/* Close */}
        <button onClick={onClose} className="absolute top-4 right-4 z-10 text-gray-500 hover:text-white transition-colors">
          <X size={20} />
        </button>

        <div className="p-6 space-y-6">
          {/* Section 1: Decision Summary */}
          <div className="flex items-center gap-6 flex-wrap">
            <div className="relative flex items-center justify-center">
              <ConfidenceArc value={data.confidence} size={90} />
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className={cn("text-lg font-bold",
                  data.action === "BUY" ? "text-green-400" : data.action === "SELL" ? "text-red-400" : "text-yellow-400"
                )}>{data.action}</span>
                <span className="text-xs text-gray-400">{(data.confidence * 100).toFixed(0)}%</span>
              </div>
            </div>
            <div className="flex-1">
              <h2 className="text-xl font-bold text-white">{data.symbol}</h2>
              <p className="text-sm text-gray-400">Price at signal: ${data.market_snapshot.price.toLocaleString()}</p>
              <p className="text-xs text-gray-500">{new Date(data.timestamp).toLocaleString()}</p>
            </div>
            {/* Model agreement */}
            <div className="card p-3 text-xs space-y-2 min-w-[200px]">
              <div className="flex items-center gap-2">
                <span className={cn("h-2 w-2 rounded-full", data.models_agree ? "bg-green-500" : "bg-yellow-500")} />
                <span className="text-gray-300">{data.models_agree ? "Models agree" : "Models disagree"}</span>
              </div>
              <div className="space-y-1">
                {data.tcn_prediction ? (<>
                <div className="flex justify-between"><span className="text-gray-500">TCN</span><span className="text-gray-300">{data.tcn_prediction.direction} ({(data.tcn_prediction.confidence * 100).toFixed(0)}%)</span></div>
                <div className="h-1.5 rounded-full bg-gray-700"><div className="h-1.5 rounded-full bg-purple-500 transition-all" style={{ width: `${data.tcn_prediction.confidence * 100}%` }} /></div>
                </>) : <div className="text-gray-500 text-[10px]">TCN: N/A</div>}
                {data.xgb_prediction ? (<>
                <div className="flex justify-between"><span className="text-gray-500">XGBoost</span><span className="text-gray-300">{data.xgb_prediction.direction} ({(data.xgb_prediction.confidence * 100).toFixed(0)}%)</span></div>
                <div className="h-1.5 rounded-full bg-gray-700"><div className="h-1.5 rounded-full bg-blue-500 transition-all" style={{ width: `${data.xgb_prediction.confidence * 100}%` }} /></div>
                </>) : <div className="text-gray-500 text-[10px]">XGBoost: N/A</div>}
              </div>
            </div>
          </div>

          {/* Section 2: Feature Importance */}
          <div>
            <h3 className="section-title mb-3">Why This Decision</h3>
            <div className="space-y-2">
              {data.top_factors.slice(0, 8).map((f) => {
                const pct = Math.abs(f.impact) * 100;
                return (
                  <div key={f.feature} className="group relative">
                    <div className="flex items-center gap-3 text-xs">
                      <span className="w-32 shrink-0 text-gray-400 font-mono truncate">{f.feature}</span>
                      <div className="flex-1 flex items-center">
                        <div className="relative h-4 flex-1">
                          <div className="absolute left-1/2 top-0 bottom-0 w-px bg-gray-700" />
                          {f.impact >= 0 ? (
                            <div className="absolute left-1/2 top-0.5 h-3 rounded-r bg-green-500/60" style={{ width: `${pct / 2}%` }} />
                          ) : (
                            <div className="absolute top-0.5 h-3 rounded-l bg-red-500/60" style={{ width: `${pct / 2}%`, right: "50%" }} />
                          )}
                        </div>
                      </div>
                      <span className={cn("w-12 text-right font-mono", f.direction === "bullish" ? "text-green-400" : f.direction === "bearish" ? "text-red-400" : "text-gray-400")}>
                        {f.value.toFixed(1)}
                      </span>
                    </div>
                    <div className="hidden group-hover:block absolute left-32 top-full mt-1 z-20 rounded-lg bg-gray-800 border border-gray-700 p-2 text-[11px] text-gray-300 max-w-xs shadow-xl">
                      {f.description}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Section 3 & 4: Market Snapshot + Risk */}
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Market Snapshot */}
            <div className="card p-4">
              <h3 className="text-sm font-semibold text-white mb-3">Market Conditions</h3>
              <ResponsiveContainer width="100%" height={180}>
                <RadarChart data={radarData} cx="50%" cy="50%" outerRadius="70%">
                  <PolarGrid stroke="#1f2937" />
                  <PolarAngleAxis dataKey="axis" tick={{ fill: "#6b7280", fontSize: 10 }} />
                  <Radar dataKey="value" stroke="#22c55e" fill="rgba(34,197,94,0.15)" strokeWidth={1.5} />
                  <Tooltip contentStyle={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, fontSize: 11 }} />
                </RadarChart>
              </ResponsiveContainer>
              <div className="flex justify-between text-xs text-gray-500 mt-2">
                <span>Support: {data.market_snapshot.support_level != null ? `$${data.market_snapshot.support_level.toLocaleString()}` : "N/A"}</span>
                <span>Resistance: {data.market_snapshot.resistance_level != null ? `$${data.market_snapshot.resistance_level.toLocaleString()}` : "N/A"}</span>
              </div>
              {isPartial && <p className="text-[10px] text-yellow-500/80 mt-1">Limited data — detailed analysis unavailable</p>}
            </div>

            {/* Risk Profile */}
            <div className="card p-4 space-y-4">
              <h3 className="text-sm font-semibold text-white">Risk Profile</h3>
              {data.risk_assessment.risk_score != null ? (
                <RiskGauge score={data.risk_assessment.risk_score} />
              ) : (
                <p className="text-xs text-gray-500 text-center">Risk score unavailable</p>
              )}
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div><span className="text-gray-500">Position Size</span><p className="font-mono text-white">{data.risk_assessment.position_size_pct != null ? `${data.risk_assessment.position_size_pct.toFixed(1)}%` : "N/A"}</p></div>
                <div><span className="text-gray-500">R:R Ratio</span><p className="font-mono text-white">{data.risk_assessment.risk_reward_ratio != null ? data.risk_assessment.risk_reward_ratio.toFixed(2) : "N/A"}</p></div>
                <div><span className="text-gray-500">Stop Loss</span><p className="font-mono text-red-400">{data.risk_assessment.stop_loss != null ? `$${data.risk_assessment.stop_loss.toLocaleString()}` : "N/A"}</p></div>
                <div><span className="text-gray-500">Take Profit</span><p className="font-mono text-green-400">{data.risk_assessment.take_profit != null ? `$${data.risk_assessment.take_profit.toLocaleString()}` : "N/A"}</p></div>
              </div>
              {data.risk_assessment.risk_reward_ratio != null && (<>
              {/* R:R visual bar */}
              <div className="flex h-3 rounded-full overflow-hidden">
                <div className="bg-red-500/60" style={{ width: `${(1 / (1 + data.risk_assessment.risk_reward_ratio)) * 100}%` }} />
                <div className="bg-green-500/60 flex-1" />
              </div>
              <div className="flex justify-between text-[10px] text-gray-500">
                <span>Risk</span><span>Reward</span>
              </div>
              </>)}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
