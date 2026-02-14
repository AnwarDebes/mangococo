"use client";

import { useQuery } from "@tanstack/react-query";
import { getPortfolio, getPositions, getTrades } from "@/lib/api";

export function usePortfolio() {
  return useQuery({
    queryKey: ["portfolio"],
    queryFn: getPortfolio,
    refetchInterval: 5000,
  });
}

export function usePositions() {
  return useQuery({
    queryKey: ["positions"],
    queryFn: getPositions,
    refetchInterval: 2000,
  });
}

export function useTrades() {
  return useQuery({
    queryKey: ["trades"],
    queryFn: getTrades,
    refetchInterval: 10000,
  });
}
