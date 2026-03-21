import { useQuery } from "@tanstack/react-query";
import {
  getPortfolio,
  getPositions,
  getSignals,
  getSentiment,
  getModelStatus,
  getSystemHealth,
  getAllTickers,
  getPredictionFactors,
  getResourceMetrics,
  getFearGreed,
  getGlobalMarket,
  getTrades,
} from "@/lib/api";

export function useNerveCenterData() {
  const portfolio = useQuery({ queryKey: ["portfolio"], queryFn: getPortfolio, refetchInterval: 5000 });
  const positions = useQuery({ queryKey: ["positions"], queryFn: getPositions, refetchInterval: 5000 });
  const signals = useQuery({ queryKey: ["signals"], queryFn: getSignals, refetchInterval: 3000 });
  const sentiment = useQuery({ queryKey: ["sentiment"], queryFn: getSentiment, refetchInterval: 10000 });
  const models = useQuery({ queryKey: ["models"], queryFn: getModelStatus, refetchInterval: 15000 });
  const health = useQuery({ queryKey: ["system-health"], queryFn: getSystemHealth, refetchInterval: 10000 });
  const tickers = useQuery({ queryKey: ["tickers"], queryFn: getAllTickers, refetchInterval: 5000 });
  const factors = useQuery({ queryKey: ["factors"], queryFn: getPredictionFactors, refetchInterval: 10000 });
  const resources = useQuery({ queryKey: ["resources"], queryFn: getResourceMetrics, refetchInterval: 10000 });
  const fearGreed = useQuery({ queryKey: ["fear-greed"], queryFn: () => getFearGreed(7), refetchInterval: 60000 });
  const globalMarket = useQuery({ queryKey: ["global-market"], queryFn: getGlobalMarket, refetchInterval: 30000 });
  const trades = useQuery({ queryKey: ["trades", "nerve"], queryFn: () => getTrades(50), refetchInterval: 15000 });

  return {
    portfolio: portfolio.data,
    positions: positions.data ?? [],
    signals: signals.data ?? [],
    sentiment: sentiment.data ?? [],
    models: models.data ?? [],
    health: health.data ?? [],
    tickers: tickers.data ?? [],
    factors: factors.data ?? [],
    resources: resources.data ?? [],
    fearGreed: fearGreed.data,
    globalMarket: globalMarket.data,
    trades: trades.data?.trades ?? [],
    isLoading: portfolio.isLoading || positions.isLoading,
  };
}
