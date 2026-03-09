"use client";

import type { Signal } from "@/types";

interface Props {
  signals: Signal[];
}

export default function OracleDetail({ signals }: Props) {
  const buyCount = signals.filter((s) => s.action === "BUY").length;
  const sellCount = signals.filter((s) => s.action === "SELL").length;
  const holdCount = signals.filter((s) => s.action === "HOLD").length;
  const avgConf = signals.length > 0
    ? signals.reduce((s, sig) => s + sig.confidence, 0) / signals.length
    : 0;

  return (
    <div className="space-y-3">
      {/* Distribution */}
      <div className="flex gap-2">
        <StatBox label="BUY" value={buyCount} color="text-green-400" bg="bg-green-500/10 border-green-500/20" />
        <StatBox label="SELL" value={sellCount} color="text-red-400" bg="bg-red-500/10 border-red-500/20" />
        <StatBox label="HOLD" value={holdCount} color="text-yellow-400" bg="bg-yellow-500/10 border-yellow-500/20" />
      </div>

      {/* Avg confidence */}
      <div className="bg-gray-900/50 rounded-lg px-3 py-2 text-center">
        <div className="text-[9px] text-cyan-400 uppercase font-bold">Avg Oracle Power</div>
        <div className="text-lg font-black text-cyan-300">{(avgConf * 100).toFixed(0)}%</div>
        <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden mt-1">
          <div className="h-full rounded-full bg-gradient-to-r from-cyan-600 to-cyan-400" style={{ width: `${avgConf * 100}%` }} />
        </div>
      </div>

      {/* Recent signals */}
      <div>
        <div className="text-[9px] text-gray-500 uppercase font-bold mb-1">Recent Quests</div>
        <div className="space-y-1 max-h-[30vh] overflow-y-auto">
          {signals.slice(0, 15).map((s) => (
            <div key={s.signal_id} className="flex items-center gap-2 bg-gray-900/50 rounded px-2 py-1.5 border border-gray-800/50">
              <span className={`w-5 h-5 flex items-center justify-center rounded text-[9px] font-black ${
                s.action === "BUY" ? "bg-green-500/20 text-green-400" :
                s.action === "SELL" ? "bg-red-500/20 text-red-400" :
                "bg-yellow-500/20 text-yellow-400"
              }`}>
                {s.action === "BUY" ? "▲" : s.action === "SELL" ? "▼" : "●"}
              </span>
              <div className="flex-1">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-bold text-white">{s.symbol.replace("/USDT", "")}</span>
                  <span className="text-[9px] text-gray-500">
                    {new Date(s.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </span>
                </div>
                <div className="flex items-center gap-1">
                  <div className="flex-1 h-1 bg-gray-800 rounded-full overflow-hidden">
                    <div className="h-full rounded-full" style={{
                      width: `${s.confidence * 100}%`,
                      backgroundColor: s.confidence > 0.7 ? "#22c55e" : s.confidence > 0.4 ? "#f59e0b" : "#6b7280",
                    }} />
                  </div>
                  <span className="text-[8px] text-gray-400">{(s.confidence * 100).toFixed(0)}%</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function StatBox({ label, value, color, bg }: { label: string; value: number; color: string; bg: string }) {
  return (
    <div className={`flex-1 rounded-lg px-2 py-1.5 border text-center ${bg}`}>
      <div className={`text-lg font-black ${color}`}>{value}</div>
      <div className="text-[8px] text-gray-500 uppercase">{label}</div>
    </div>
  );
}
