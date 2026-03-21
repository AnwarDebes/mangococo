"use client";

import { useState } from "react";
import SignalFeed from "@/components/panels/SignalFeed";
import PriceChart from "@/components/charts/PriceChart";
import AITimeline from "@/components/panels/AITimeline";
import ManualTradePanel from "@/components/panels/ManualTradePanel";
import MultiTimeframe from "@/components/trading/MultiTimeframe";

export default function TradingPage() {
  const [showManualTrade, setShowManualTrade] = useState(false);
  const [viewMode, setViewMode] = useState<"single" | "multi">("single");

  return (
    <div className="space-y-4 sm:space-y-6 animate-fade-in">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-white">
            Live <span className="text-goblin-gradient">Trading</span>
          </h1>
          <p className="text-xs sm:text-sm text-gray-400">
            Real-time chart, signals, and positions
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-gray-700 overflow-hidden">
            <button
              onClick={() => setViewMode("single")}
              className={`px-2 py-1 text-[10px] font-medium transition-colors ${viewMode === "single" ? "bg-goblin-500/20 text-goblin-400" : "text-gray-500 hover:text-white"}`}
            >
              Single Chart
            </button>
            <button
              onClick={() => setViewMode("multi")}
              className={`px-2 py-1 text-[10px] font-medium transition-colors ${viewMode === "multi" ? "bg-goblin-500/20 text-goblin-400" : "text-gray-500 hover:text-white"}`}
            >
              Multi-Timeframe
            </button>
          </div>
          <button
            onClick={() => setShowManualTrade(true)}
            className="btn-goblin text-xs sm:text-sm px-3 sm:px-4 py-2 whitespace-nowrap"
          >
            Manual Trade
          </button>
        </div>
      </div>

      {viewMode === "multi" ? (
        <MultiTimeframe />
      ) : (
      <div className="grid gap-4 sm:gap-6 lg:grid-cols-3">
        {/* Chart Area */}
        <div className="lg:col-span-2">
          <PriceChart />
        </div>

        {/* Signal Feed */}
        <div className="lg:col-span-1">
          <SignalFeed />
        </div>
      </div>
      )}

      {/* AI Decision Timeline */}
      <AITimeline />

      {/* Manual Trade Side Panel */}
      {showManualTrade && (
        <ManualTradePanel onClose={() => setShowManualTrade(false)} />
      )}
    </div>
  );
}
