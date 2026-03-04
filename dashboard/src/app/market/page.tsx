"use client";

import FearGreedPanel from "@/components/market/FearGreedPanel";
import GlobalStatsPanel from "@/components/market/GlobalStatsPanel";
import BitcoinNetworkPanel from "@/components/market/BitcoinNetworkPanel";
import TopMoversTable from "@/components/market/TopMoversTable";
import TrendingPanel from "@/components/market/TrendingPanel";
import DefiOverviewPanel from "@/components/market/DefiOverviewPanel";
import StablecoinPanel from "@/components/market/StablecoinPanel";
import DexVolumePanel from "@/components/market/DexVolumePanel";

export default function MarketIntelPage() {
  return (
    <div className="space-y-4 sm:space-y-6 animate-fade-in">
      <div>
        <h1 className="text-xl sm:text-2xl font-bold text-white">
          Market <span className="text-goblin-gradient">Intelligence</span>
        </h1>
        <p className="text-xs sm:text-sm text-gray-400">
          Real-time crypto market overview from 5 free public APIs
        </p>
      </div>

      {/* Top row: Fear & Greed, Global Stats, BTC Network */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <FearGreedPanel />
        <GlobalStatsPanel />
        <BitcoinNetworkPanel />
      </div>

      {/* Top Movers Table */}
      <TopMoversTable />

      {/* Trending + DeFi */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <TrendingPanel />
        <DefiOverviewPanel />
      </div>

      {/* Stablecoin + DEX Volume */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <StablecoinPanel />
        <DexVolumePanel />
      </div>
    </div>
  );
}
