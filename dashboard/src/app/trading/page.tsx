"use client";

import { usePositions } from "@/hooks/usePortfolio";
import PositionCard from "@/components/panels/PositionCard";
import SignalFeed from "@/components/panels/SignalFeed";

export default function TradingPage() {
  const { data: positions, isLoading } = usePositions();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Live Trading</h1>
        <p className="text-sm text-gray-400">
          Real-time chart, signals, and positions
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Chart Area */}
        <div className="lg:col-span-2">
          <div className="card">
            <h3 className="mb-3 font-semibold text-white">Price Chart</h3>
            <div
              id="chart-container"
              className="flex h-[400px] items-center justify-center rounded-lg border border-gray-700 bg-gray-950"
            >
              <div className="text-center text-gray-500">
                <p className="text-lg font-medium">TradingView Chart</p>
                <p className="mt-1 text-sm">
                  Connect lightweight-charts to render live price data
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Signal Feed */}
        <div className="lg:col-span-1">
          <SignalFeed />
        </div>
      </div>

      {/* Current Positions */}
      <div>
        <h2 className="mb-3 text-lg font-semibold text-white">
          Active Positions
        </h2>
        {isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="card animate-pulse h-36" />
            ))}
          </div>
        ) : !positions || positions.length === 0 ? (
          <div className="card text-center text-sm text-gray-500 py-8">
            No active positions
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {positions.map((pos, i) => (
              <PositionCard key={`${pos.symbol}-${i}`} position={pos} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
