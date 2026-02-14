"use client";

import {
  Trophy,
  TrendingUp,
  TrendingDown,
  BarChart3,
} from "lucide-react";
import { usePortfolio, usePositions, useTrades } from "@/hooks/usePortfolio";
import { formatPercent, cn, getPnlColor } from "@/lib/utils";
import PortfolioCard from "@/components/panels/PortfolioCard";
import PositionCard from "@/components/panels/PositionCard";
import TradeHistory from "@/components/panels/TradeHistory";
import SystemHealth from "@/components/panels/SystemHealth";

function MetricCard({
  label,
  value,
  icon: Icon,
  color,
}: {
  label: string;
  value: string;
  icon: React.ElementType;
  color?: string;
}) {
  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-gray-500">{label}</p>
        <Icon size={16} className={color || "text-gray-500"} />
      </div>
      <p className={cn("mt-1 text-2xl font-bold", color || "text-white")}>
        {value}
      </p>
    </div>
  );
}

export default function DashboardPage() {
  const { data: portfolio, isLoading: loadingPortfolio } = usePortfolio();
  const { data: positions, isLoading: loadingPositions } = usePositions();
  const { data: trades, isLoading: loadingTrades } = useTrades();

  // Compute metrics from trades
  const winRate =
    trades && trades.length > 0
      ? (trades.filter((t) => t.realized_pnl > 0).length / trades.length) * 100
      : 0;

  const totalTrades = trades?.length || 0;

  // Simplified Sharpe approximation
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

  // Max drawdown from PnL percentages
  const maxDrawdown =
    trades && trades.length > 0
      ? Math.min(...trades.map((t) => t.pnl_pct), 0)
      : 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <p className="text-sm text-gray-400">Real-time portfolio overview</p>
      </div>

      {/* Portfolio Value */}
      <PortfolioCard portfolio={portfolio} isLoading={loadingPortfolio} />

      {/* Metrics Row */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard
          label="Win Rate"
          value={formatPercent(winRate).replace("+", "")}
          icon={Trophy}
          color="text-mango-500"
        />
        <MetricCard
          label="Sharpe Ratio"
          value={sharpe.toFixed(2)}
          icon={TrendingUp}
          color={sharpe >= 1 ? "text-profit" : "text-neutral"}
        />
        <MetricCard
          label="Max Drawdown"
          value={formatPercent(maxDrawdown)}
          icon={TrendingDown}
          color={getPnlColor(maxDrawdown)}
        />
        <MetricCard
          label="Total Trades"
          value={totalTrades.toString()}
          icon={BarChart3}
        />
      </div>

      {/* Open Positions */}
      <div>
        <h2 className="mb-3 text-lg font-semibold text-white">
          Open Positions
        </h2>
        {loadingPositions ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="card animate-pulse h-36" />
            ))}
          </div>
        ) : !positions || positions.length === 0 ? (
          <div className="card text-center text-sm text-gray-500 py-8">
            No open positions
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {positions.map((pos, i) => (
              <PositionCard key={`${pos.symbol}-${i}`} position={pos} />
            ))}
          </div>
        )}
      </div>

      {/* Recent Trades */}
      <TradeHistory trades={trades} isLoading={loadingTrades} />

      {/* System Health */}
      <div>
        <h2 className="mb-3 text-lg font-semibold text-white">
          System Health
        </h2>
        <SystemHealth />
      </div>
    </div>
  );
}
