"use client";

import { ArrowUpRight, ArrowDownRight, Shield, Target } from "lucide-react";
import {
  formatCurrency,
  formatPrice,
  formatPercent,
  getTimeSince,
  getPnlColor,
  cn,
} from "@/lib/utils";
import type { Position } from "@/types";

interface PositionCardProps {
  position: Position;
}

export default function PositionCard({ position }: PositionCardProps) {
  const pnlPercent =
    position.entry_price > 0
      ? ((position.current_price - position.entry_price) /
          position.entry_price) *
        100 *
        (position.side === "long" ? 1 : -1)
      : 0;

  return (
    <div className="card-hover">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg font-bold text-white">
            {position.symbol}
          </span>
          <span
            className={cn(
              "badge",
              position.side === "long" ? "badge-buy" : "badge-sell"
            )}
          >
            {position.side.toUpperCase()}
          </span>
        </div>
        <span className="text-xs text-gray-500">
          {getTimeSince(position.opened_at)}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3">
        <div>
          <p className="text-xs text-gray-500">Entry</p>
          <p className="text-sm font-mono text-gray-300">
            ${formatPrice(position.entry_price)}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-500">Current</p>
          <p className="text-sm font-mono text-white">
            ${formatPrice(position.current_price)}
          </p>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between">
        <div>
          <p className="text-xs text-gray-500">Unrealized PnL</p>
          <div
            className={cn(
              "flex items-center gap-1 font-semibold",
              getPnlColor(position.unrealized_pnl)
            )}
          >
            {position.unrealized_pnl >= 0 ? (
              <ArrowUpRight size={14} />
            ) : (
              <ArrowDownRight size={14} />
            )}
            <span>{formatCurrency(Math.abs(position.unrealized_pnl))}</span>
            <span className="text-xs">({formatPercent(pnlPercent)})</span>
          </div>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-4 text-xs text-gray-500">
        <div className="flex items-center gap-1">
          <Shield size={12} className="text-red-400" />
          <span>SL: ${formatPrice(position.stop_loss_price)}</span>
        </div>
        <div className="flex items-center gap-1">
          <Target size={12} className="text-green-400" />
          <span>TP: ${formatPrice(position.take_profit_price)}</span>
        </div>
      </div>
    </div>
  );
}
