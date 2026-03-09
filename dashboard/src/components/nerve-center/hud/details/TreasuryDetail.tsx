"use client";

import type { PortfolioState, Position } from "@/types";

interface Props {
  portfolio?: PortfolioState;
  positions: Position[];
}

export default function TreasuryDetail({ portfolio, positions }: Props) {
  const totalValue = portfolio?.total_value ?? 0;
  const dailyPnl = portfolio?.daily_pnl ?? 0;
  const cash = portfolio?.cash_balance ?? 0;
  const posValue = portfolio?.positions_value ?? 0;
  const isProfitable = dailyPnl >= 0;

  const cashPct = totalValue > 0 ? (cash / totalValue) * 100 : 0;
  const investedPct = 100 - cashPct;

  return (
    <div className="space-y-3">
      {/* Total Value */}
      <div className="text-center">
        <div className="text-[10px] text-amber-400 uppercase font-bold">Total Treasury</div>
        <div className="text-2xl font-black text-amber-300" style={{ textShadow: "0 0 10px rgba(251,191,36,0.3)" }}>
          ${totalValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}
        </div>
      </div>

      {/* P&L */}
      <div className="flex justify-between bg-gray-900/50 rounded-lg px-3 py-2">
        <div>
          <div className="text-[9px] text-gray-500">Daily Gold</div>
          <div className={`text-sm font-bold ${isProfitable ? "text-green-400" : "text-red-400"}`}>
            {isProfitable ? "+" : ""}${dailyPnl.toFixed(2)}
          </div>
        </div>
        <div className="text-right">
          <div className="text-[9px] text-gray-500">Reserves</div>
          <div className="text-sm font-bold text-blue-300">${cash.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
        </div>
      </div>

      {/* Allocation bar */}
      <div>
        <div className="text-[9px] text-gray-500 mb-1">Allocation</div>
        <div className="flex h-3 rounded-full overflow-hidden bg-gray-800">
          <div className="bg-amber-500 transition-all" style={{ width: `${investedPct}%` }} />
          <div className="bg-blue-500 transition-all" style={{ width: `${cashPct}%` }} />
        </div>
        <div className="flex justify-between text-[9px] mt-0.5">
          <span className="text-amber-400">Invested {investedPct.toFixed(0)}%</span>
          <span className="text-blue-400">Cash {cashPct.toFixed(0)}%</span>
        </div>
      </div>

      {/* Position summary */}
      <div className="bg-gray-900/50 rounded-lg px-3 py-2">
        <div className="text-[9px] text-gray-500 mb-1">Army Summary</div>
        <div className="flex justify-between text-[10px]">
          <span className="text-gray-400">Warriors</span>
          <span className="text-white font-bold">{positions.length}</span>
        </div>
        <div className="flex justify-between text-[10px]">
          <span className="text-gray-400">Winning</span>
          <span className="text-green-400">{positions.filter((p) => p.unrealized_pnl >= 0).length}</span>
        </div>
        <div className="flex justify-between text-[10px]">
          <span className="text-gray-400">Losing</span>
          <span className="text-red-400">{positions.filter((p) => p.unrealized_pnl < 0).length}</span>
        </div>
      </div>
    </div>
  );
}
