"use client";

import FundingHeatmap from "@/components/derivatives/FundingHeatmap";
import OpenInterestChart from "@/components/derivatives/OpenInterestChart";
import LongShortChart from "@/components/derivatives/LongShortChart";
import MarketPositioning from "@/components/derivatives/MarketPositioning";

export default function DerivativesPage() {
  return (
    <div className="space-y-4 sm:space-y-6 animate-fade-in">
      <div>
        <h1 className="text-xl sm:text-2xl font-bold text-white">
          Derivatives <span className="text-goblin-gradient">Intelligence</span>
        </h1>
        <p className="text-xs sm:text-sm text-gray-400">
          Futures market positioning, funding rates, and leverage analysis
        </p>
      </div>

      {/* Funding Rate Heatmap */}
      <FundingHeatmap />

      {/* Open Interest + Long/Short side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <OpenInterestChart />
        <LongShortChart />
      </div>

      {/* Market Positioning Summary */}
      <MarketPositioning />
    </div>
  );
}
