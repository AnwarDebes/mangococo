"use client";

import { useMemo } from "react";
import { useNerveCenterData } from "@/hooks/useNerveCenterData";
import { useKingdomEvents } from "@/hooks/useKingdomEvents";
import { useNerveCenterStore } from "./NerveCenterStore";
import ZoneNavBar from "./hud/ZoneNavBar";
import Minimap from "./hud/Minimap";
import EventFeed from "./hud/EventFeed";
import ZoneDetailPanel from "./hud/ZoneDetailPanel";

export default function NerveCenterHUD() {
  const data = useNerveCenterData();
  const isPlaying = useNerveCenterStore((s) => s.isPlaying);
  const nearestZone = useNerveCenterStore((s) => s.nearestZone);

  // Activate the event system
  useKingdomEvents();

  const totalValue = data.portfolio?.total_value ?? 0;
  const dailyPnl = data.portfolio?.daily_pnl ?? 0;
  const cashBalance = data.portfolio?.cash_balance ?? 0;
  const isProfitable = dailyPnl >= 0;

  const winRate = useMemo(() => {
    if (!data.trades.length) return null;
    const wins = data.trades.filter((t) => t.realized_pnl > 0).length;
    return ((wins / data.trades.length) * 100).toFixed(0);
  }, [data.trades]);

  const healthyCount = data.health.filter((s) => s.status === "healthy").length;

  return (
    <div className="absolute inset-0 pointer-events-none z-10">
      {/* ── TOP BAR: Kingdom Header ── */}
      <div className="absolute top-0 left-0 right-0">
        <div className="flex items-center justify-between px-4 py-2">
          {/* Kingdom Name */}
          <div className="pointer-events-auto">
            <div className="bg-gradient-to-r from-amber-900/90 via-yellow-900/80 to-amber-900/90 backdrop-blur-md border border-amber-600/40 rounded-lg px-4 py-2 flex items-center gap-3 shadow-xl">
              <div
                className="text-amber-400 text-lg font-black tracking-wide"
                style={{ textShadow: "0 0 10px rgba(251,191,36,0.3)" }}
              >
                Goblin Trading Kingdom
              </div>
              <div className="w-px h-6 bg-amber-600/40" />
              <div className="text-amber-200 text-sm font-bold">
                ${totalValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </div>
            </div>
          </div>

          {/* Resource badges */}
          <div className="flex gap-2 pointer-events-auto">
            <ResourceBadge
              icon="💰"
              label="Gold/Day"
              value={`${isProfitable ? "+" : ""}$${dailyPnl.toFixed(2)}`}
              color={isProfitable ? "text-green-400" : "text-red-400"}
            />
            <ResourceBadge icon="💎" label="Reserves" value={`$${cashBalance.toLocaleString(undefined, { maximumFractionDigits: 0 })}`} color="text-blue-300" />
            <ResourceBadge icon="⚔" label="Army" value={`${data.positions.length}`} color="text-purple-300" />
            <ResourceBadge icon="🎯" label="Win Rate" value={winRate ? `${winRate}%` : "N/A"} color="text-cyan-300" />
            <ResourceBadge icon="💚" label="Services" value={`${healthyCount}/${data.health.length}`} color={healthyCount === data.health.length ? "text-green-400" : "text-yellow-400"} />
          </div>
        </div>
      </div>

      {/* ── Event Feed (left) ── */}
      <EventFeed />

      {/* ── Minimap (top-right) ── */}
      <Minimap />

      {/* ── Zone Detail Panel (right, context-sensitive) ── */}
      <ZoneDetailPanel />

      {/* ── Zone Navigation Bar (bottom) ── */}
      <ZoneNavBar />

      {/* ── Alert Banner (top-center) ── */}
      {data.health.some((s) => s.status !== "healthy") && (
        <div className="absolute top-16 left-1/2 -translate-x-1/2 pointer-events-none">
          <div className="bg-red-900/80 backdrop-blur-md border border-red-500/50 rounded-xl px-4 py-2 animate-pulse shadow-xl">
            <div className="flex items-center gap-2">
              <span className="text-red-400 text-lg">⚠</span>
              <div>
                <div className="text-red-300 text-xs font-bold">Kingdom Alert!</div>
                <div className="text-red-200/70 text-[10px]">
                  {data.health.filter((s) => s.status !== "healthy").length} goblin(s) need healing
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Click to Play overlay ── */}
      {!isPlaying && (
        <div className="absolute bottom-24 left-1/2 -translate-x-1/2 pointer-events-none">
          <div className="bg-amber-900/80 backdrop-blur-md border border-amber-500/50 rounded-xl px-6 py-3 shadow-2xl animate-pulse">
            <div className="text-amber-300 text-sm font-bold text-center">Click to Enter the Kingdom</div>
            <div className="text-amber-200/60 text-[10px] text-center mt-1">WASD to walk, Mouse to look around, Shift to sprint</div>
          </div>
        </div>
      )}

      {/* ── Controls hint (bottom-right) ── */}
      {isPlaying && (
        <div className="absolute bottom-16 right-3 pointer-events-none hidden lg:block">
          <div className="bg-gray-950/70 backdrop-blur rounded-lg px-2 py-1.5 text-[9px] text-gray-500 space-y-0.5">
            <div><kbd className="bg-gray-800 rounded px-1 text-gray-400">WASD</kbd> Walk</div>
            <div><kbd className="bg-gray-800 rounded px-1 text-gray-400">Shift</kbd> Sprint</div>
            <div><kbd className="bg-gray-800 rounded px-1 text-gray-400">Mouse</kbd> Look</div>
            <div><kbd className="bg-gray-800 rounded px-1 text-gray-400">ESC</kbd> Release cursor</div>
            {nearestZone && (
              <div className="text-amber-400 mt-1 font-bold">Near: {nearestZone}</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ResourceBadge({ icon, label, value, color }: { icon: string; label: string; value: string; color: string }) {
  return (
    <div className="bg-gray-950/90 backdrop-blur-md border border-gray-700/50 rounded-lg px-2.5 py-1.5 flex items-center gap-2 shadow-lg">
      <span className="text-sm">{icon}</span>
      <div>
        <div className="text-[9px] text-gray-500 uppercase">{label}</div>
        <div className={`text-xs font-bold ${color}`}>{value}</div>
      </div>
    </div>
  );
}
