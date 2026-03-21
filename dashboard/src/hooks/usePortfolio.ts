"use client";

import { useQuery, keepPreviousData } from "@tanstack/react-query";
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

export function useTrades(
  page = 1,
  pageSize = 20,
  sort: "desc" | "asc" = "desc"
) {
  const offset = (page - 1) * pageSize;
  return useQuery({
    queryKey: ["trades", page, pageSize, sort],
    queryFn: () => getTrades(pageSize, offset, sort),
    refetchInterval: 10000,
    placeholderData: keepPreviousData,
  });
}
