"use client";

import { TrendingUp, TrendingDown } from "lucide-react";
import { formatCurrency, formatPercent, getPnlColor, cn } from "@/lib/utils";
import type { PortfolioState } from "@/types";

interface PortfolioCardProps {
  portfolio: PortfolioState | undefined;
  isLoading: boolean;
}

export default function PortfolioCard({
  portfolio,
  isLoading,
}: PortfolioCardProps) {
  if (isLoading || !portfolio) {
    return (
      <div className="card col-span-full animate-pulse">
        <div className="h-8 w-48 rounded bg-gray-700" />
        <div className="mt-2 h-12 w-64 rounded bg-gray-700" />
        <div className="mt-3 h-5 w-32 rounded bg-gray-700" />
      </div>
    );
  }

  const pnlPositive = portfolio.daily_pnl >= 0;
  const pnlPercent =
    portfolio.total_value > 0
      ? (portfolio.daily_pnl / portfolio.total_value) * 100
      : 0;

  return (
    <div className="card col-span-full bg-gradient-to-br from-gray-900 to-gray-800 border-mango-500/20">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-gray-400">Total Portfolio Value</p>
          <p className="mt-1 text-4xl font-bold tracking-tight text-white">
            {formatCurrency(portfolio.total_value)}
          </p>
          <div className="mt-3 flex items-center gap-3">
            <div
              className={cn(
                "flex items-center gap-1",
                getPnlColor(portfolio.daily_pnl)
              )}
            >
              {pnlPositive ? (
                <TrendingUp size={18} />
              ) : (
                <TrendingDown size={18} />
              )}
              <span className="text-lg font-semibold">
                {formatCurrency(Math.abs(portfolio.daily_pnl))}
              </span>
              <span className="text-sm">({formatPercent(pnlPercent)})</span>
            </div>
            <span className="text-xs text-gray-500">24h</span>
          </div>
        </div>
        <div className="text-right space-y-2">
          <div>
            <p className="text-xs text-gray-500">Cash Balance</p>
            <p className="text-sm font-medium text-gray-300">
              {formatCurrency(portfolio.cash_balance)}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500">Positions Value</p>
            <p className="text-sm font-medium text-gray-300">
              {formatCurrency(portfolio.positions_value)}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500">Open Positions</p>
            <p className="text-sm font-medium text-mango-400">
              {portfolio.open_positions}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
