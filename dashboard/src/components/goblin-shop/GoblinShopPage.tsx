"use client";

import dynamic from "next/dynamic";
import { useCallback, useMemo } from "react";
import { useShopData } from "./useShopData";
import { useGoblinShopStore } from "./GoblinShopStore";
import { generateTreasureMaps } from "@/lib/arena-utils";
import DistrictNav from "./navigation/DistrictNav";
import ActivityFeed from "./features/ActivityFeed";
import CoinCounter from "./effects/CoinCounter";
import { cn } from "@/lib/utils";

// 3D hero — SSR disabled (Three.js)
const InteractiveBazaar3D = dynamic(() => import("./hero/InteractiveBazaar3D"), { ssr: false });

// Districts — dynamically loaded (only one visible at a time)
const ForgeOfStrategies = dynamic(() => import("./districts/ForgeOfStrategies"));
const OracleEmporium = dynamic(() => import("./districts/OracleEmporium"));
const AlchemistWorkshop = dynamic(() => import("./districts/AlchemistWorkshop"));
const HallOfChampions = dynamic(() => import("./districts/HallOfChampions"));
const GoblinVault = dynamic(() => import("./districts/GoblinVault"));
const FamiliarDen = dynamic(() => import("./districts/FamiliarDen"), { ssr: false });
const EnchantmentWorkshop = dynamic(() => import("./districts/EnchantmentWorkshop"));
const GoblinArena = dynamic(() => import("./districts/GoblinArena"));
const TreasureMaps = dynamic(() => import("./districts/TreasureMaps"));
const GuildHall = dynamic(() => import("./districts/GuildHall"));
const ProphecyChamber = dynamic(() => import("./districts/ProphecyChamber"));
const SkinWorkshop = dynamic(() => import("./districts/SkinWorkshop"));

// Features — dynamically loaded (only one visible at a time)
const MysteryChests = dynamic(() => import("./features/MysteryChests"));
const WheelOfFortune = dynamic(() => import("./features/WheelOfFortune"));
const BattlePass = dynamic(() => import("./features/BattlePass"));

// Modals — dynamically loaded (conditionally rendered)
const StrategyDetailModal = dynamic(() => import("./modals/StrategyDetailModal"));
const PurchaseModal = dynamic(() => import("./modals/PurchaseModal"));
const StakingModal = dynamic(() => import("./modals/StakingModal"));
const CraftingModal = dynamic(() => import("./modals/CraftingModal"));

const TIER_STYLES: Record<string, { color: string; label: string }> = {
  bronze: { color: "text-orange-400", label: "🥉 Bronze" },
  silver: { color: "text-gray-300", label: "🥈 Silver" },
  gold: { color: "text-gold-400", label: "🥇 Gold" },
  diamond: { color: "text-cyan-400", label: "💎 Diamond" },
  goblin_king: { color: "text-amber-400", label: "👑 Goblin King" },
};

export default function GoblinShopPage() {
  const data = useShopData();
  const store = useGoblinShopStore();
  const { activeDistrict } = store;

  const effectiveBalance = Math.max(0, data.playerProfile.gbln_balance - store.spentGBLN);
  const tierStyle = TIER_STYLES[data.playerProfile.tier] || TIER_STYLES.bronze;

  const selectedStrategy = store.selectedStrategyId
    ? data.strategies.find((s) => s.id === store.selectedStrategyId)
    : null;

  const treasureMaps = useMemo(
    () => generateTreasureMaps(data.trades),
    [data.trades]
  );

  const playerWinRate = useMemo(() => {
    if (data.trades.length === 0) return 50;
    const wins = data.trades.filter((t) => t.realized_pnl > 0).length;
    return (wins / data.trades.length) * 100;
  }, [data.trades]);

  const handleSpendGBLN = useCallback(
    (amount: number) => {
      store.purchaseItem("misc", "misc", amount);
    },
    [store]
  );

  // No-op for earn (would integrate with backend in production)
  const handleEarnGBLN = useCallback((_amount: number) => {
    // In production, this would call an API to credit GBLN
  }, []);

  if (data.isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="text-4xl mb-3 animate-bounce">⚒</div>
          <p className="text-gray-500 text-sm">Loading the Grand Bazaar...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950">
      {/* 3D Interactive Bazaar */}
      <InteractiveBazaar3D
        activeDistrict={activeDistrict}
        onDistrictClick={(d) => store.setDistrict(d as typeof activeDistrict)}
      />

      {/* Player Profile Bar */}
      <div className="bg-gray-900/80 backdrop-blur border-y border-goblin-500/20 px-2 sm:px-4 py-2 sm:py-3">
        <div className="max-w-7xl mx-auto flex flex-wrap items-center gap-2 sm:gap-4">
          {/* Left: Avatar + Name */}
          <div className="flex items-center gap-2 sm:gap-3">
            <div className="w-8 h-8 sm:w-10 sm:h-10 rounded-full bg-goblin-500/20 border border-goblin-500/30 flex items-center justify-center text-sm sm:text-lg shrink-0">
              🧌
            </div>
            <div>
              <div className="text-xs sm:text-sm font-bold text-white">{data.playerProfile.goblinsName}</div>
              <div className="text-[9px] sm:text-[10px] text-gray-500">{data.playerProfile.title}</div>
            </div>
          </div>

          {/* Center: Level + XP Bar */}
          <div className="flex items-center gap-2 sm:gap-3 flex-1 min-w-[140px] sm:min-w-[200px]">
            <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-goblin-500/20 border border-goblin-500/30 flex items-center justify-center text-[10px] sm:text-xs font-bold text-goblin-400 shrink-0">
              {data.playerProfile.level}
            </div>
            <div className="flex-1 max-w-[200px]">
              <div className="flex justify-between text-[9px] sm:text-[10px] text-gray-500 mb-0.5">
                <span>Lv.{data.playerProfile.level}</span>
                <span>{data.playerProfile.xp} / {data.playerProfile.xp + data.playerProfile.xpToNextLevel} XP</span>
              </div>
              <div className="h-1.5 sm:h-2 bg-gray-800 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-goblin-600 to-goblin-400 rounded-full transition-all duration-1000"
                  style={{
                    width: `${(data.playerProfile.xp / (data.playerProfile.xp + data.playerProfile.xpToNextLevel)) * 100}%`,
                  }}
                />
              </div>
            </div>
          </div>

          {/* Right: GBLN Balance + Tier */}
          <div className="flex items-center gap-2 sm:gap-4">
            <CoinCounter amount={effectiveBalance} size="md" />
            <span className={cn("text-[10px] sm:text-xs font-bold px-1.5 sm:px-2 py-0.5 rounded-full bg-gray-800 border border-gray-700 whitespace-nowrap", tierStyle.color)}>
              {tierStyle.label}
            </span>
          </div>
        </div>
      </div>

      {/* Live Activity Feed */}
      <ActivityFeed />

      {/* District Navigation */}
      <DistrictNav />

      {/* District Content */}
      <div key={activeDistrict} className="animate-fade-in max-w-7xl mx-auto">
        {/* Marketplace */}
        {activeDistrict === "forge" && <ForgeOfStrategies strategies={data.strategies} />}
        {activeDistrict === "oracle" && <OracleEmporium signalPacks={data.signalPacks} />}
        {activeDistrict === "alchemist" && <AlchemistWorkshop />}
        {activeDistrict === "enchantment" && (
          <EnchantmentWorkshop
            strategies={data.strategies}
            balance={effectiveBalance}
            onSpendGBLN={handleSpendGBLN}
          />
        )}
        {activeDistrict === "skins" && (
          <SkinWorkshop balance={effectiveBalance} onSpendGBLN={handleSpendGBLN} />
        )}
        {activeDistrict === "prophecy" && (
          <ProphecyChamber balance={effectiveBalance} onSpendGBLN={handleSpendGBLN} />
        )}

        {/* Adventures */}
        {activeDistrict === "arena" && (
          <GoblinArena
            playerWinRate={playerWinRate}
            playerLevel={data.playerProfile.level}
            balance={effectiveBalance}
            onSpendGBLN={handleSpendGBLN}
            onEarnGBLN={handleEarnGBLN}
          />
        )}
        {activeDistrict === "treasure" && <TreasureMaps maps={treasureMaps} />}
        {activeDistrict === "guild" && <GuildHall />}
        {activeDistrict === "champions" && (
          <HallOfChampions
            achievements={data.achievements}
            quests={data.quests}
            playerProfile={data.playerProfile}
          />
        )}
        {activeDistrict === "vault" && <GoblinVault />}
        {activeDistrict === "familiar" && (
          <FamiliarDen
            balance={effectiveBalance}
            onSpendGBLN={(amount) =>
              store.purchaseItem("familiar", "ability", amount)
            }
          />
        )}

        {/* Rewards */}
        {activeDistrict === "chests" && (
          <div className="p-4 space-y-4 animate-fade-in">
            <div>
              <h2 className="text-lg font-bold text-white flex items-center gap-2">📦 Mystery Chests</h2>
              <p className="text-xs text-gray-500 mt-0.5">Open chests to discover rare strategies, enchantments, and GBLN.</p>
            </div>
            <MysteryChests balance={effectiveBalance} onSpendGBLN={handleSpendGBLN} />
          </div>
        )}
        {activeDistrict === "wheel" && (
          <div className="p-4 space-y-4 animate-fade-in">
            <div>
              <h2 className="text-lg font-bold text-white flex items-center gap-2">🎰 Wheel of Fortune</h2>
              <p className="text-xs text-gray-500 mt-0.5">Spin the wheel for a chance to win GBLN, XP, and chests!</p>
            </div>
            <WheelOfFortune
              balance={effectiveBalance}
              onEarnReward={(_segment) => {
                // In production, credit the reward
              }}
            />
          </div>
        )}
        {activeDistrict === "battlepass" && (
          <div className="p-4 space-y-4 animate-fade-in">
            <BattlePass
              playerXP={data.playerProfile.xp}
              balance={effectiveBalance}
              onSpendGBLN={handleSpendGBLN}
            />
          </div>
        )}
      </div>

      {/* Modals */}
      {selectedStrategy && (
        <StrategyDetailModal
          artifact={selectedStrategy}
          trades={data.trades}
          isOwned={store.ownedStrategies.includes(selectedStrategy.id)}
          onClose={() => store.selectStrategy(null)}
          onPurchase={(a) =>
            store.setPurchase({ type: "strategy", id: a.id, name: a.name, price: a.priceTier })
          }
        />
      )}
      <PurchaseModal balance={effectiveBalance} />
      <StakingModal balance={effectiveBalance} />
      <CraftingModal />
    </div>
  );
}
