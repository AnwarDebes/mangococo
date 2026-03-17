"use client";

import { useState, useMemo } from "react";
import { useAILogs, useAIStats, useAITimeline } from "@/hooks/useAILogs";
import AILogEntry from "@/components/logs/AILogEntry";
import AILogFilters from "@/components/logs/AILogFilters";
import AIStatsCards from "@/components/logs/AIStatsCards";
import type { AIDecisionChain } from "@/types";

const CHAIN_OUTCOME_COLORS: Record<string, string> = {
  profitable: "text-green-400",
  loss: "text-red-400",
  pending: "text-amber-400",
  rejected: "text-gray-400",
};

export default function LogsPage() {
  const [category, setCategory] = useState("");
  const [level, setLevel] = useState("");
  const [symbol, setSymbol] = useState("");
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"feed" | "chains">("feed");

  const { entries, isLoading, isLive, toggleLive, liveCount } = useAILogs({
    category: category || undefined,
    level: level || undefined,
    symbol: symbol || undefined,
    limit: 200,
  });

  const { data: stats, isLoading: statsLoading } = useAIStats();
  const { data: chains } = useAITimeline();

  // Client-side search filter
  const filteredEntries = useMemo(() => {
    if (!search) return entries;
    const q = search.toLowerCase();
    return entries.filter(
      (e) =>
        e.message.toLowerCase().includes(q) ||
        e.service.toLowerCase().includes(q) ||
        e.category.toLowerCase().includes(q)
    );
  }, [entries, search]);

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-white">
            AI Nerve <span className="text-goblin-gradient">Monitor</span>
          </h1>
          <p className="text-xs sm:text-sm text-gray-400">
            Real-time AI activity logging and decision tracking
          </p>
        </div>

        {/* Activity Pulse */}
        <div className="flex items-center gap-2">
          {isLive && (
            <div className="flex items-center gap-1">
              {[
                "bg-green-500",
                "bg-amber-500",
                "bg-blue-500",
                "bg-purple-500",
                "bg-red-500",
              ].map((bgClass, i) => (
                <span
                  key={bgClass}
                  className={`w-1.5 h-1.5 rounded-full ${bgClass} animate-pulse`}
                  style={{ animationDelay: `${i * 0.2}s` }}
                />
              ))}
            </div>
          )}
          <span className="text-xs text-gray-500">
            {filteredEntries.length} events
          </span>
        </div>
      </div>

      {/* Stats Cards */}
      <AIStatsCards stats={stats} isLoading={statsLoading} />

      {/* View Toggle + Filters */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setView("feed")}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              view === "feed"
                ? "bg-goblin-500/20 text-goblin-400 border border-goblin-500/30"
                : "bg-gray-800 text-gray-400 border border-gray-700 hover:border-gray-600"
            }`}
          >
            Activity Feed
          </button>
          <button
            onClick={() => setView("chains")}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              view === "chains"
                ? "bg-goblin-500/20 text-goblin-400 border border-goblin-500/30"
                : "bg-gray-800 text-gray-400 border border-gray-700 hover:border-gray-600"
            }`}
          >
            Decision Chains
          </button>
        </div>

        <AILogFilters
          category={category}
          level={level}
          symbol={symbol}
          search={search}
          onCategoryChange={setCategory}
          onLevelChange={setLevel}
          onSymbolChange={setSymbol}
          onSearchChange={setSearch}
          isLive={isLive}
          onToggleLive={toggleLive}
          liveCount={liveCount}
        />
      </div>

      {/* Main Content */}
      {view === "feed" ? (
        <div className="space-y-1">
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <div
                  key={i}
                  className="h-10 bg-gray-800/50 rounded-lg animate-pulse"
                />
              ))}
            </div>
          ) : filteredEntries.length === 0 ? (
            <div className="card text-center py-12">
              <div className="text-4xl mb-3">🔍</div>
              <p className="text-gray-400 text-sm">
                No AI activity logs yet. Logs will appear as services generate
                predictions, signals, and trades.
              </p>
              <p className="text-gray-500 text-xs mt-2">
                Try triggering a chat message or waiting for the next prediction
                cycle.
              </p>
            </div>
          ) : (
            filteredEntries.map((entry) => (
              <AILogEntry key={entry.id} entry={entry} />
            ))
          )}
        </div>
      ) : (
        /* Decision Chains View */
        <div className="space-y-3">
          {!chains || chains.length === 0 ? (
            <div className="card text-center py-12">
              <div className="text-4xl mb-3">🔗</div>
              <p className="text-gray-400 text-sm">
                No decision chains yet. Chains form when predictions lead to
                signals, which lead to trades.
              </p>
            </div>
          ) : (
            chains.map((chain: AIDecisionChain) => (
              <div
                key={chain.chain_id}
                className="card border-l-2 border-l-goblin-500/50"
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-gray-500">
                      {chain.chain_id.slice(0, 8)}
                    </span>
                    {chain.symbol && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-goblin-500/20 text-goblin-400 font-mono">
                        {chain.symbol}
                      </span>
                    )}
                  </div>
                  {chain.outcome && (
                    <span
                      className={`text-xs font-medium ${
                        CHAIN_OUTCOME_COLORS[chain.outcome] || "text-gray-400"
                      }`}
                    >
                      {chain.outcome}
                    </span>
                  )}
                </div>

                {/* Chain events */}
                <div className="relative pl-4 space-y-1">
                  <div className="absolute left-1.5 top-1 bottom-1 w-px bg-goblin-500/30" />
                  {chain.events.map((event, i) => (
                    <div key={event.id || i} className="relative flex items-center gap-2">
                      <div className="absolute -left-[14px] w-2 h-2 rounded-full bg-goblin-500 border border-gray-900" />
                      <span className="font-mono text-[10px] text-gray-500">
                        {new Date(event.timestamp).toLocaleTimeString("en-US", {
                          hour12: false,
                          hour: "2-digit",
                          minute: "2-digit",
                          second: "2-digit",
                        })}
                      </span>
                      <span className="text-xs text-gray-300">
                        {event.message}
                      </span>
                    </div>
                  ))}
                </div>

                <div className="mt-2 text-[10px] text-gray-600">
                  {new Date(chain.started_at).toLocaleString()}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
