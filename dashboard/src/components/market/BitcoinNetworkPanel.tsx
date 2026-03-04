"use client";

import { useQuery } from "@tanstack/react-query";
import { getBitcoinNetwork } from "@/lib/api";
import { cn } from "@/lib/utils";

function getCongestion(count: number): { label: string; color: string } {
  if (count < 20000) return { label: "Clear", color: "text-profit" };
  if (count <= 50000) return { label: "Normal", color: "text-yellow-400" };
  return { label: "Congested", color: "text-loss" };
}

export default function BitcoinNetworkPanel() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["bitcoin-network"],
    queryFn: getBitcoinNetwork,
    refetchInterval: 60000,
  });

  if (isError) return (
    <div className="card text-center py-8">
      <p className="text-sm text-gray-400">Data temporarily unavailable</p>
      <button onClick={() => refetch()} className="mt-2 text-xs text-goblin-500 hover:underline">Retry</button>
    </div>
  );

  if (isLoading || !data) return <div className="card skeleton-shimmer h-56" />;

  const hashrate = (data.mining?.currentHashrate || 0) / 1e18;
  const mempoolCount = data.mempool?.count || 0;
  const fastestFee = data.fees?.fastestFee || 0;
  const diffChange = data.difficulty?.difficultyChange || 0;
  const diffProgress = data.difficulty?.progressPercent || 0;
  const congestion = getCongestion(mempoolCount);

  return (
    <div className="card">
      <h3 className="section-title mb-3">BTC Network</h3>
      <div className="grid grid-cols-2 gap-2">
        <div className="p-2 rounded-lg bg-gray-900/50 text-center">
          <p className="text-[10px] text-gray-500">Hashrate</p>
          <p className="text-sm font-bold text-white">{hashrate.toFixed(1)} EH/s</p>
        </div>
        <div className="p-2 rounded-lg bg-gray-900/50 text-center">
          <p className="text-[10px] text-gray-500">Mempool</p>
          <p className="text-sm font-bold text-white">{mempoolCount.toLocaleString()}</p>
          <p className={cn("text-[9px] font-medium", congestion.color)}>{congestion.label}</p>
        </div>
        <div className="p-2 rounded-lg bg-gray-900/50 text-center">
          <p className="text-[10px] text-gray-500">Fastest Fee</p>
          <p className="text-sm font-bold text-white">{fastestFee} sat/vB</p>
        </div>
        <div className="p-2 rounded-lg bg-gray-900/50 text-center">
          <p className="text-[10px] text-gray-500">Difficulty</p>
          <p className={cn("text-sm font-bold", diffChange >= 0 ? "text-profit" : "text-loss")}>
            {diffChange >= 0 ? "+" : ""}{diffChange.toFixed(1)}%
          </p>
        </div>
      </div>
      {/* Difficulty progress bar */}
      <div className="mt-3">
        <div className="flex justify-between text-[10px] text-gray-500 mb-1">
          <span>Difficulty Adjustment</span>
          <span>{diffProgress.toFixed(1)}%</span>
        </div>
        <div className="h-1.5 rounded-full bg-gray-800">
          <div className="h-1.5 rounded-full bg-goblin-500 transition-all" style={{ width: `${Math.min(diffProgress, 100)}%` }} />
        </div>
      </div>
    </div>
  );
}
