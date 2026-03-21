"use client";

import { useMemo } from "react";
import {
  Trophy,
  TrendingUp,
  TrendingDown,
  BarChart3,
} from "lucide-react";
import { usePortfolio, usePositions, useTrades } from "@/hooks/usePortfolio";
import { formatPercent, cn, getPnlColor, computeMaxDrawdown } from "@/lib/utils";
import PortfolioCard from "@/components/panels/PortfolioCard";
import PositionCard from "@/components/panels/PositionCard";
import TradeHistory from "@/components/panels/TradeHistory";
import SystemHealth from "@/components/panels/SystemHealth";
import GoblinCoin3D from "@/components/3d/GoblinCoin3D";
import PortfolioTreemap from "@/components/charts/PortfolioTreemap";
import { useTilt } from "@/hooks/useTilt";
import { useCountUp } from "@/hooks/useCountUp";
import type { PortfolioState } from "@/types";

function MetricCard({
  label,
  value,
  numericValue,
  icon: Icon,
  color,
  delay = 0,
}: {
  label: string;
  value: string;
  numericValue?: number;
  icon: React.ElementType;
  color?: string;
  delay?: number;
}) {
  const tilt = useTilt(2);
  const animatedValue = useCountUp(numericValue ?? 0, 800, 2);
  const displayValue = numericValue !== undefined
    ? (label === "Total Trades" ? Math.round(animatedValue).toString() : animatedValue.toFixed(2) + (label === "Win Rate" ? "%" : ""))
    : value;

  return (
    <div
      className="card-hover hover-glow animate-slide-up"
      style={{ animationDelay: `${delay}ms`, ...tilt.style }}
      onMouseMove={tilt.onMouseMove}
      onMouseLeave={tilt.onMouseLeave}
    >
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-gray-500 truncate">{label}</p>
        <Icon size={16} className={cn("shrink-0", color || "text-gray-500")} />
      </div>
      <p className={cn("mt-1 text-xl sm:text-2xl font-bold truncate", color || "text-white")}>
        {displayValue}
      </p>
    </div>
  );
}

export default function DashboardPage() {
  const { data: rawPortfolio, isLoading: loadingPortfolio } = usePortfolio();
  const { data: positions, isLoading: loadingPositions } = usePositions();
  const { data: tradesData, isLoading: loadingTrades } = useTrades(1, 50);
  const trades = tradesData?.trades;

  // Reconcile portfolio values with actual positions data so all numbers
  // displayed on the dashboard are internally consistent.
  const portfolio: PortfolioState | undefined = useMemo(() => {
    if (!rawPortfolio) return undefined;

    // Use the API's total_value directly (computed by the paper executor
    // from actual balances + current prices).  Recalculating from the
    // positions array can diverge when the position service is out of sync.
    const totalValue = rawPortfolio.total_value;
    const cashBalance = rawPortfolio.cash_balance;
    const positionsValue = totalValue - cashBalance > 0 ? totalValue - cashBalance : 0;
    const openPositions = positions ? positions.length : rawPortfolio.open_positions;

    return {
      total_value: totalValue,
      cash_balance: cashBalance,
      positions_value: positionsValue,
      daily_pnl: rawPortfolio.daily_pnl,
      open_positions: openPositions,
    };
  }, [rawPortfolio, positions]);

  const winRate =
    trades && trades.length > 0
      ? (trades.filter((t) => t.realized_pnl > 0).length / trades.length) * 100
      : 0;

  const totalTrades = trades?.length || 0;

  const avgReturn =
    trades && trades.length > 0
      ? trades.reduce((sum, t) => sum + t.pnl_pct, 0) / trades.length
      : 0;
  const stdDev =
    trades && trades.length > 1
      ? Math.sqrt(
          trades.reduce((sum, t) => sum + Math.pow(t.pnl_pct - avgReturn, 2), 0) /
            (trades.length - 1)
        )
      : 1;
  const sharpe = stdDev > 0 ? (avgReturn / stdDev) * Math.sqrt(252) : 0;
  const hasSufficientTrades = (trades?.length ?? 0) >= 5;

  const maxDrawdown = computeMaxDrawdown(trades ?? [], portfolio?.total_value ?? 1000);

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* Hero Section */}
      <div className="relative particles-bg rounded-xl sm:rounded-2xl border border-goblin-500/10 bg-gradient-to-br from-goblin-900/20 via-gray-900 to-gray-950 p-4 sm:p-6 overflow-hidden">
        <div className="relative z-10 flex items-center justify-between">
          <div>
            <h1 className="text-xl sm:text-3xl font-bold text-white animate-fade-in">
              Goblin <span className="text-goblin-gradient">Dashboard</span>
            </h1>
            <p className="text-xs sm:text-sm text-gray-400 mt-1">
              Real-time AI-powered portfolio overview
            </p>
          </div>
          <div className="hidden md:block">
            <GoblinCoin3D size={80} />
          </div>
        </div>
      </div>

      {/* Portfolio Value */}
      <PortfolioCard portfolio={portfolio} isLoading={loadingPortfolio} />

      {/* Metrics Row */}
      <div className="grid grid-cols-2 gap-2 sm:gap-3 xl:grid-cols-4">
        <MetricCard
          label="Win Rate"
          value={formatPercent(winRate).replace("+", "")}
          numericValue={winRate}
          icon={Trophy}
          color="text-goblin-500"
          delay={0}
        />
        <MetricCard
          label="Sharpe Ratio"
          value={hasSufficientTrades ? sharpe.toFixed(2) : "N/A"}
          numericValue={hasSufficientTrades ? sharpe : undefined}
          icon={TrendingUp}
          color={hasSufficientTrades && sharpe >= 1 ? "text-profit" : "text-neutral"}
          delay={100}
        />
        <MetricCard
          label="Max Drawdown"
          value={formatPercent(maxDrawdown)}
          numericValue={maxDrawdown}
          icon={TrendingDown}
          color={getPnlColor(maxDrawdown)}
          delay={200}
        />
        <MetricCard
          label="Total Trades"
          value={totalTrades.toString()}
          numericValue={totalTrades}
          icon={BarChart3}
          delay={300}
        />
      </div>

      {/* Portfolio Treemap */}
      <PortfolioTreemap portfolio={portfolio} positions={positions} />

      {/* Open Positions */}
      <div>
        <h2 className="section-title mb-3">Open Positions</h2>
        {loadingPositions ? (
          <div className="grid gap-3 sm:gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="card skeleton-shimmer h-36" />
            ))}
          </div>
        ) : !positions || positions.length === 0 ? (
          <div className="card text-center text-sm text-gray-500 py-8">
            No open positions
          </div>
        ) : (
          <div className="grid gap-3 sm:gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
            {positions.map((pos, i) => (
              <PositionCard key={`${pos.symbol}-${i}`} position={pos} />
            ))}
          </div>
        )}
      </div>

      {/* Recent Trades */}
      <TradeHistory />

      {/* System Health */}
      <div>
        <h2 className="section-title mb-3">System Health</h2>
        <SystemHealth />
      </div>
    </div>
  );
}
