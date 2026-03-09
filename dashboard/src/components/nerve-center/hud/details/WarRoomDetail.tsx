"use client";

import type { Position } from "@/types";

interface Props {
  positions: Position[];
}

export default function WarRoomDetail({ positions }: Props) {
  const totalPnl = positions.reduce((s, p) => s + p.unrealized_pnl, 0);
  const isProfitable = totalPnl >= 0;

  return (
    <div className="space-y-2">
      {/* Total P&L */}
      <div className="text-center bg-gray-900/50 rounded-lg px-3 py-2">
        <div className="text-[9px] text-green-400 uppercase font-bold">Battle P&L</div>
        <div className={`text-xl font-black ${isProfitable ? "text-green-400" : "text-red-400"}`}>
          {isProfitable ? "+" : ""}${totalPnl.toFixed(2)}
        </div>
      </div>

      {/* Position cards */}
      <div className="space-y-1.5">
        {positions.map((pos, i) => {
          const profiting = pos.unrealized_pnl >= 0;
          const pct = pos.entry_price > 0
            ? ((pos.current_price - pos.entry_price) / pos.entry_price) * 100
            : 0;
          const posValue = pos.amount * pos.current_price;

          return (
            <div
              key={pos.symbol + i}
              className={`rounded-lg px-2.5 py-2 border ${
                profiting ? "bg-green-500/5 border-green-500/20" : "bg-red-500/5 border-red-500/20"
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-bold text-white">{pos.symbol}</span>
                  <span className={`text-[9px] font-bold px-1 rounded ${pos.side === "long" ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"}`}>
                    {pos.side.toUpperCase()}
                  </span>
                </div>
                <span className={`text-xs font-bold ${profiting ? "text-green-400" : "text-red-400"}`}>
                  {profiting ? "+" : ""}{pct.toFixed(1)}%
                </span>
              </div>

              {/* Price bar */}
              <div className="flex justify-between text-[9px] text-gray-400 mb-1">
                <span>Entry: ${pos.entry_price.toLocaleString()}</span>
                <span>Now: ${pos.current_price.toLocaleString()}</span>
              </div>

              {/* P&L bar */}
              <div className="h-1 bg-gray-800 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${profiting ? "bg-green-500" : "bg-red-500"}`}
                  style={{ width: `${Math.min(100, Math.abs(pct) * 2)}%` }}
                />
              </div>

              <div className="flex justify-between text-[9px] mt-1">
                <span className="text-gray-500">${posValue.toFixed(0)} value</span>
                <span className={profiting ? "text-green-400" : "text-red-400"}>
                  {profiting ? "+" : ""}${pos.unrealized_pnl.toFixed(2)}
                </span>
              </div>
            </div>
          );
        })}
        {positions.length === 0 && (
          <div className="text-center py-3 text-gray-600 text-[10px] italic">No warriors deployed</div>
        )}
      </div>
    </div>
  );
}
