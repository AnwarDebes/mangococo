"use client";

import { useTrades } from "@/hooks/usePortfolio";
import { formatPercent, cn, getPnlColor, computeMaxDrawdown } from "@/lib/utils";
import EquityCurve from "@/components/charts/EquityCurve";
import TradeHistory from "@/components/panels/TradeHistory";
import StressTest from "@/components/panels/StressTest";
import StrategyLeaderboard from "@/components/panels/StrategyLeaderboard";
import PerformanceReport from "@/components/panels/PerformanceReport";
import CorrelationMatrix from "@/components/analytics/CorrelationMatrix";
import TradeCalendar from "@/components/analytics/TradeCalendar";
import BenchmarkComparison from "@/components/analytics/BenchmarkComparison";
import DrawdownChart from "@/components/analytics/DrawdownChart";

function StatCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="card">
      <p className="text-xs font-medium text-gray-500">{label}</p>
      <p className={cn("mt-1 text-xl font-bold", color || "text-white")}>
        {value}
      </p>
    </div>
  );
}

export default function AnalyticsPage() {
  const { data: tradesData, isLoading } = useTrades(1, 50);
  const trades = tradesData?.trades;

  // Compute metrics
  const winTrades = trades?.filter((t) => t.realized_pnl > 0) || [];
  const lossTrades = trades?.filter((t) => t.realized_pnl < 0) || [];
  const totalTrades = trades?.length || 0;
  const winRate = totalTrades > 0 ? (winTrades.length / totalTrades) * 100 : 0;

  const avgReturn =
    totalTrades > 0
      ? (trades?.reduce((s, t) => s + t.pnl_pct, 0) || 0) / totalTrades
      : 0;
  const stdDev =
    totalTrades > 1
      ? Math.sqrt(
          (trades?.reduce(
            (s, t) => s + Math.pow(t.pnl_pct - avgReturn, 2),
            0
          ) || 0) /
            (totalTrades - 1)
        )
      : 1;
  const sharpe = stdDev > 0 ? (avgReturn / stdDev) * Math.sqrt(252) : 0;

  // Sortino: downside deviation
  const downsideDev =
    totalTrades > 1
      ? Math.sqrt(
          (trades
            ?.filter((t) => t.pnl_pct < 0)
            .reduce((s, t) => s + Math.pow(t.pnl_pct, 2), 0) || 0) /
            totalTrades
        )
      : 1;
  const sortino = downsideDev > 0 ? (avgReturn / downsideDev) * Math.sqrt(252) : 0;

  const grossProfit = winTrades.reduce((s, t) => s + t.realized_pnl, 0);
  const grossLoss = Math.abs(lossTrades.reduce((s, t) => s + t.realized_pnl, 0));
  const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? Infinity : 0;

  const hasSufficientTrades = totalTrades >= 5;

  const maxDrawdown = computeMaxDrawdown(trades ?? [], 1000);

  // Build equity curve from trades using real starting capital ($1000)
  const equityData =
    trades && trades.length > 0
      ? (() => {
          let balance = 1000;
          const sorted = [...trades].sort(
            (a, b) =>
              new Date(a.closed_at).getTime() - new Date(b.closed_at).getTime()
          );
          return sorted.map((t) => {
            balance += t.realized_pnl;
            return {
              date: new Date(t.closed_at).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
              }),
              value: balance,
            };
          });
        })()
      : [];

  // Strategy distribution
  const strategyMap = new Map<string, number>();
  trades?.forEach((t) => {
    strategyMap.set(t.strategy, (strategyMap.get(t.strategy) || 0) + 1);
  });
  const strategies = Array.from(strategyMap.entries()).sort(
    (a, b) => b[1] - a[1]
  );

  return (
    <div className="space-y-4 sm:space-y-6">
      <div>
        <h1 className="text-xl sm:text-2xl font-bold text-white">Performance Analytics</h1>
        <p className="text-xs sm:text-sm text-gray-400">
          Detailed trading performance metrics
        </p>
      </div>

      {/* Key Metrics */}
      <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-3 xl:grid-cols-5">
        <StatCard
          label="Sharpe Ratio"
          value={hasSufficientTrades ? sharpe.toFixed(2) : "N/A"}
          color={hasSufficientTrades && sharpe >= 1 ? "text-profit" : "text-neutral"}
        />
        <StatCard
          label="Sortino Ratio"
          value={hasSufficientTrades ? sortino.toFixed(2) : "N/A"}
          color={hasSufficientTrades && sortino >= 1 ? "text-profit" : "text-neutral"}
        />
        <StatCard
          label="Win Rate"
          value={formatPercent(winRate).replace("+", "")}
          color="text-goblin-500"
        />
        <StatCard
          label="Profit Factor"
          value={profitFactor === Infinity ? "---" : profitFactor.toFixed(2)}
          color={profitFactor >= 1.5 ? "text-profit" : "text-neutral"}
        />
        <StatCard
          label="Max Drawdown"
          value={formatPercent(maxDrawdown)}
          color={getPnlColor(maxDrawdown)}
        />
      </div>

      {/* Equity Curve */}
      <div className="card">
        <h3 className="mb-4 font-semibold text-white">Equity Curve</h3>
        <EquityCurve data={equityData} />
      </div>

      {/* Drawdown Chart */}
      <DrawdownChart trades={trades ?? []} />

      {/* Benchmark Comparison */}
      <BenchmarkComparison trades={trades ?? []} />

      {/* Trade Calendar Heatmap */}
      <TradeCalendar trades={trades ?? []} />

      {/* Correlation Matrix */}
      <CorrelationMatrix />

      {/* Strategy Distribution */}
      <div className="card">
        <h3 className="mb-4 font-semibold text-white">
          Trade Distribution by Strategy
        </h3>
        {strategies.length === 0 ? (
          <p className="text-sm text-gray-500">No trade data available</p>
        ) : (
          <div className="space-y-3">
            {strategies.map(([strategy, count]) => (
              <div key={strategy}>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-gray-300">{strategy}</span>
                  <span className="text-gray-400">
                    {count} trades ({((count / totalTrades) * 100).toFixed(1)}%)
                  </span>
                </div>
                <div className="mt-1 h-2 rounded-full bg-gray-700">
                  <div
                    className="h-2 rounded-full bg-goblin-500"
                    style={{
                      width: `${(count / totalTrades) * 100}%`,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Strategy Leaderboard */}
      <StrategyLeaderboard trades={trades ?? []} />

      {/* Portfolio Stress Tester */}
      <StressTest />

      {/* Performance Report */}
      <PerformanceReport
        trades={trades ?? []}
        sharpe={sharpe}
        winRate={winRate}
        maxDrawdown={maxDrawdown}
        profitFactor={profitFactor}
      />

      {/* Full Trade History */}
      <TradeHistory />
    </div>
  );
}
