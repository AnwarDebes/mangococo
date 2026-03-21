"use client";

import { useQuery } from "@tanstack/react-query";
import {
  getPortfolio,
  getPositions,
  getTrades,
  getSignals,
  getSentiment,
  getModelStatus,
  getSystemHealth,
  getAllTickers,
} from "@/lib/api";
import {
  generateStrategyArtifacts,
  generateSignalPacks,
  generateAchievements,
  generateQuests,
  computeLevel,
  computeTier,
} from "@/lib/shop-utils";
import type { PlayerProfile } from "@/types/shop";
import { useMemo } from "react";

export function useShopData() {
  const portfolio = useQuery({ queryKey: ["portfolio"], queryFn: getPortfolio, refetchInterval: 10000 });
  const positions = useQuery({ queryKey: ["positions"], queryFn: getPositions, refetchInterval: 10000 });
  const trades = useQuery({ queryKey: ["trades", "shop"], queryFn: () => getTrades(50), refetchInterval: 15000 });
  const signals = useQuery({ queryKey: ["signals"], queryFn: getSignals, refetchInterval: 5000 });
  const sentiment = useQuery({ queryKey: ["sentiment"], queryFn: getSentiment, refetchInterval: 15000 });
  const models = useQuery({ queryKey: ["models"], queryFn: getModelStatus, refetchInterval: 20000 });
  const health = useQuery({ queryKey: ["system-health"], queryFn: getSystemHealth, refetchInterval: 20000 });
  const tickers = useQuery({ queryKey: ["tickers"], queryFn: getAllTickers, refetchInterval: 10000 });

  const tradesList = trades.data?.trades ?? [];
  const signalsList = signals.data ?? [];
  const sentimentList = sentiment.data ?? [];
  const modelsList = models.data ?? [];
  const positionsList = positions.data ?? [];
  const portfolioData = portfolio.data;

  const strategies = useMemo(
    () => generateStrategyArtifacts(tradesList, modelsList, signalsList),
    [tradesList, modelsList, signalsList]
  );

  const signalPacks = useMemo(
    () => generateSignalPacks(signalsList, sentimentList),
    [signalsList, sentimentList]
  );

  const achievements = useMemo(
    () =>
      portfolioData
        ? generateAchievements(portfolioData, tradesList, positionsList, signalsList, modelsList)
        : [],
    [portfolioData, tradesList, positionsList, signalsList, modelsList]
  );

  const quests = useMemo(
    () => (portfolioData ? generateQuests(tradesList, signalsList, portfolioData) : []),
    [tradesList, signalsList, portfolioData]
  );

  const xp = useMemo(() => {
    const tradeXp = tradesList.length * 10;
    const winXp = tradesList.filter((t) => t.realized_pnl > 0).length * 5;
    const achievementXp = achievements.filter((a) => a.isUnlocked).length * 100;
    return tradeXp + winXp + achievementXp;
  }, [tradesList, achievements]);

  const { level, xpToNext } = computeLevel(xp);

  const playerProfile: PlayerProfile = useMemo(
    () => ({
      goblinsName: "Goblin Trader",
      title:
        level >= 50
          ? "Goblin King"
          : level >= 30
            ? "Master Trader"
            : level >= 10
              ? "Apprentice"
              : "Novice",
      level,
      xp,
      xpToNextLevel: xpToNext,
      gbln_balance: Math.floor(xp * 0.5),
      gbln_staked: 0,
      totalEarned: Math.floor(xp * 0.5),
      rank: 1,
      tier: computeTier(level),
      joinedAt:
        tradesList.length > 0
          ? tradesList[tradesList.length - 1].created_at
          : new Date().toISOString(),
      tradingDays: new Set(tradesList.map((t) => new Date(t.created_at).toDateString())).size,
      achievementsUnlocked: achievements.filter((a) => a.isUnlocked).length,
      strategiesOwned: strategies.filter((s) => s.isOwned).length,
    }),
    [level, xp, xpToNext, tradesList, achievements, strategies]
  );

  return {
    portfolio: portfolioData,
    positions: positionsList,
    trades: tradesList,
    signals: signalsList,
    sentiment: sentimentList,
    models: modelsList,
    health: health.data ?? [],
    tickers: tickers.data ?? [],
    strategies,
    signalPacks,
    achievements,
    quests,
    playerProfile,
    isLoading: portfolio.isLoading || trades.isLoading,
  };
}
