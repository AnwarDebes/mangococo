"use client";

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAlertStore, type AlertCondition } from "@/stores/alertStore";
import { useNotificationStore } from "@/stores/notificationStore";
import { getAllTickers, getFearGreed, getDerivativesFunding } from "@/lib/api";

function evaluateCondition(
  condition: AlertCondition,
  context: {
    tickers: Map<string, number>;
    fearGreed: number;
    fundingRates: Map<string, number>;
  }
): boolean {
  switch (condition.type) {
    case "price_above": {
      const price = context.tickers.get(condition.symbol) || 0;
      return price > 0 && price > condition.value;
    }
    case "price_below": {
      const price = context.tickers.get(condition.symbol) || 0;
      return price > 0 && price < condition.value;
    }
    case "fear_greed_above":
      return context.fearGreed > 0 && context.fearGreed > condition.value;
    case "fear_greed_below":
      return context.fearGreed > 0 && context.fearGreed < condition.value;
    case "funding_rate_extreme": {
      const rate = context.fundingRates.get(condition.symbol) || 0;
      return Math.abs(rate) > condition.threshold;
    }
    default:
      return false;
  }
}

export function useAlertEvaluator() {
  const alerts = useAlertStore((s) => s.alerts);
  const markTriggered = useAlertStore((s) => s.markTriggered);
  const addNotification = useNotificationStore((s) => s.addNotification);

  const { data: tickerData } = useQuery({
    queryKey: ["alert-tickers"],
    queryFn: getAllTickers,
    refetchInterval: 15000,
  });

  const { data: fgData } = useQuery({
    queryKey: ["alert-fear-greed"],
    queryFn: () => getFearGreed(1),
    refetchInterval: 300000,
  });

  const { data: fundingData } = useQuery({
    queryKey: ["alert-funding"],
    queryFn: getDerivativesFunding,
    refetchInterval: 60000,
  });

  useEffect(() => {
    // Build context
    const tickers = new Map<string, number>();
    if (tickerData) {
      for (const t of tickerData) {
        tickers.set(t.symbol, parseFloat(t.lastPrice || t.price || "0"));
      }
    }

    const fearGreed = fgData?.data?.[0] ? parseInt(fgData.data[0].value, 10) : 0;

    const fundingRates = new Map<string, number>();
    if (fundingData?.symbols) {
      for (const s of fundingData.symbols) {
        fundingRates.set(s.symbol, s.current_rate * 100);
      }
    }

    const context = { tickers, fearGreed, fundingRates };

    for (const alert of alerts) {
      if (!alert.enabled || alert.triggered) continue;
      const fired = evaluateCondition(alert.condition, context);
      if (fired) {
        markTriggered(alert.id);
        addNotification({
          type: "price",
          message: `Alert: ${alert.name}`,
          color: "gold",
        });
      }
    }
  }, [tickerData, fgData, fundingData, alerts, markTriggered, addNotification]);
}
