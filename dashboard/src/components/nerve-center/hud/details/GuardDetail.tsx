"use client";

import { useMemo } from "react";
import type { Position, SystemHealth } from "@/types";

interface Props {
  positions: Position[];
  health: SystemHealth[];
}

export default function GuardDetail({ positions, health }: Props) {
  const losingPositions = positions.filter((p) => p.unrealized_pnl < 0);
  const totalLoss = losingPositions.reduce((s, p) => s + Math.abs(p.unrealized_pnl), 0);
  const worstLoss = losingPositions.length > 0
    ? Math.min(...positions.map((p) => p.unrealized_pnl))
    : 0;

  const healthyCount = health.filter((s) => s.status === "healthy").length;
  const totalServices = health.length;

  const riskScore = useMemo(() => {
    if (!positions.length) return 0;
    const losingRatio = losingPositions.length / positions.length;
    const lossScore = Math.min(50, totalLoss / 10);
    const ratioScore = losingRatio * 50;
    return Math.round(Math.min(100, lossScore + ratioScore));
  }, [positions, losingPositions, totalLoss]);

  const longCount = positions.filter((p) => p.side === "long").length;
  const shortCount = positions.filter((p) => p.side === "short").length;

  const riskColor = riskScore > 70 ? "text-red-400" : riskScore > 40 ? "text-yellow-400" : "text-green-400";
  const riskBg = riskScore > 70 ? "from-red-900/30" : riskScore > 40 ? "from-yellow-900/30" : "from-green-900/30";

  return (
    <div className="space-y-3">
      {/* Risk Score */}
      <div className={`bg-gradient-to-r ${riskBg} to-transparent rounded-lg px-3 py-2 text-center`}>
        <div className="text-[9px] text-red-400 uppercase font-bold">Risk Level</div>
        <div className={`text-3xl font-black ${riskColor}`}>{riskScore}%</div>
        <div className="h-2 bg-gray-800 rounded-full overflow-hidden mt-1">
          <div className={`h-full rounded-full transition-all ${riskScore > 70 ? "bg-red-500" : riskScore > 40 ? "bg-yellow-500" : "bg-green-500"}`} style={{ width: `${riskScore}%` }} />
        </div>
      </div>

      {/* Exposure */}
      <div className="bg-gray-900/50 rounded-lg px-3 py-2">
        <div className="text-[9px] text-gray-500 uppercase font-bold mb-1">Exposure</div>
        <div className="flex h-3 rounded-full overflow-hidden bg-gray-800">
          {positions.length > 0 && (
            <>
              <div className="bg-green-500" style={{ width: `${(longCount / positions.length) * 100}%` }} />
              <div className="bg-red-500" style={{ width: `${(shortCount / positions.length) * 100}%` }} />
            </>
          )}
        </div>
        <div className="flex justify-between text-[9px] mt-0.5">
          <span className="text-green-400">{longCount} Long</span>
          <span className="text-red-400">{shortCount} Short</span>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-1.5">
        <div className="bg-gray-900/50 rounded-lg px-2 py-1.5 text-center">
          <div className="text-[9px] text-gray-500">Losing</div>
          <div className="text-sm font-bold text-red-400">{losingPositions.length}</div>
        </div>
        <div className="bg-gray-900/50 rounded-lg px-2 py-1.5 text-center">
          <div className="text-[9px] text-gray-500">Total Loss</div>
          <div className="text-sm font-bold text-red-400">${totalLoss.toFixed(2)}</div>
        </div>
        <div className="bg-gray-900/50 rounded-lg px-2 py-1.5 text-center">
          <div className="text-[9px] text-gray-500">Worst</div>
          <div className="text-sm font-bold text-red-400">${worstLoss.toFixed(2)}</div>
        </div>
        <div className="bg-gray-900/50 rounded-lg px-2 py-1.5 text-center">
          <div className="text-[9px] text-gray-500">Services</div>
          <div className={`text-sm font-bold ${healthyCount === totalServices ? "text-green-400" : "text-yellow-400"}`}>{healthyCount}/{totalServices}</div>
        </div>
      </div>

      {/* Unhealthy services */}
      {health.filter((s) => s.status !== "healthy").length > 0 && (
        <div className="bg-red-900/20 border border-red-500/20 rounded-lg px-2 py-1.5">
          <div className="text-[9px] text-red-400 font-bold mb-1">Wounded Goblins</div>
          {health.filter((s) => s.status !== "healthy").map((s) => (
            <div key={s.service_name} className="flex justify-between text-[10px]">
              <span className="text-gray-400">{s.service_name.replace(/_/g, " ")}</span>
              <span className={s.status === "down" ? "text-red-400" : "text-yellow-400"}>{s.status}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
