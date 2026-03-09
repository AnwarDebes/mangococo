"use client";

import { Html } from "@react-three/drei";
import type { Position } from "@/types";

interface PortfolioDetailPanelProps {
  position: Position;
  worldPosition: [number, number, number];
  onClose: () => void;
}

export default function PortfolioDetailPanel({ position, worldPosition, onClose }: PortfolioDetailPanelProps) {
  const isProfitable = position.unrealized_pnl >= 0;
  const pnlPct = position.entry_price > 0
    ? ((position.current_price - position.entry_price) / position.entry_price) * 100
    : 0;
  const held = Date.now() - new Date(position.opened_at).getTime();
  const heldHours = Math.floor(held / 3600000);
  const heldDays = Math.floor(heldHours / 24);

  return (
    <group position={worldPosition}>
      <Html distanceFactor={15} style={{ pointerEvents: "auto" }}>
        <div className="bg-gray-900/95 border border-goblin-500/30 rounded-lg p-3 w-56 backdrop-blur text-white">
          <div className="flex justify-between items-center mb-2">
            <span className="font-bold text-sm">{position.symbol}</span>
            <button onClick={onClose} className="text-gray-400 hover:text-white text-xs">X</button>
          </div>
          <div className="space-y-1 text-xs text-gray-300">
            <div className="flex justify-between">
              <span>Side</span>
              <span className={position.side === "long" ? "text-green-400" : "text-red-400"}>{position.side}</span>
            </div>
            <div className="flex justify-between">
              <span>Entry</span>
              <span>${position.entry_price.toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span>Current</span>
              <span>${position.current_price.toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span>Unrealized P&L</span>
              <span className={isProfitable ? "text-green-400" : "text-red-400"}>
                ${position.unrealized_pnl.toFixed(2)} ({pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%)
              </span>
            </div>
            {position.stop_loss_price > 0 && (
              <div className="flex justify-between">
                <span>Stop Loss</span>
                <span className="text-red-400">${position.stop_loss_price.toLocaleString()}</span>
              </div>
            )}
            {position.take_profit_price > 0 && (
              <div className="flex justify-between">
                <span>Take Profit</span>
                <span className="text-green-400">${position.take_profit_price.toLocaleString()}</span>
              </div>
            )}
            <div className="flex justify-between">
              <span>Held</span>
              <span>{heldDays > 0 ? `${heldDays}d ${heldHours % 24}h` : `${heldHours}h`}</span>
            </div>
          </div>
        </div>
      </Html>
    </group>
  );
}
