"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { StrategyNode } from "@/types";

interface NodeDef {
  name: string;
  category: string;
  type: "trigger" | "condition" | "action";
  defaultParams: Record<string, number | string | boolean>;
}

const NODE_DEFS: Record<string, NodeDef[]> = {
  Triggers: [
    { name: "Price Cross", category: "Price crosses MA or level", type: "trigger", defaultParams: { target: "EMA20", direction: "above" } },
    { name: "RSI Threshold", category: "RSI crosses level", type: "trigger", defaultParams: { period: 14, threshold: 30, direction: "below" } },
    { name: "MACD Cross", category: "MACD line crosses signal", type: "trigger", defaultParams: { fast: 12, slow: 26, signal: 9 } },
    { name: "Volume Spike", category: "Volume exceeds Nx average", type: "trigger", defaultParams: { multiplier: 2.0, period: 20 } },
    { name: "Sentiment Shift", category: "Sentiment change > X pts", type: "trigger", defaultParams: { threshold: 10 } },
    { name: "Whale Alert", category: "Whale tx > $X detected", type: "trigger", defaultParams: { min_usd: 5000000 } },
    { name: "Schedule", category: "Fires at interval", type: "trigger", defaultParams: { interval: "1h" } },
  ],
  Conditions: [
    { name: "AND Gate", category: "All inputs must be true", type: "condition", defaultParams: {} },
    { name: "OR Gate", category: "Any input must be true", type: "condition", defaultParams: {} },
    { name: "Confidence Filter", category: "AI confidence > threshold", type: "condition", defaultParams: { min_confidence: 0.7 } },
    { name: "Time Filter", category: "Active during hours", type: "condition", defaultParams: { start_hour: 8, end_hour: 22 } },
    { name: "Position Check", category: "Check position state", type: "condition", defaultParams: { check: "no_position" } },
  ],
  Actions: [
    { name: "Buy", category: "Place buy order", type: "action", defaultParams: { size_pct: 10, order_type: "market" } },
    { name: "Sell", category: "Place sell order", type: "action", defaultParams: { size_pct: 100, order_type: "market" } },
    { name: "Set Stop-Loss", category: "Stop-loss % below entry", type: "action", defaultParams: { percent: 2 } },
    { name: "Set Take-Profit", category: "Take-profit % above entry", type: "action", defaultParams: { percent: 3 } },
    { name: "Alert Only", category: "Send notification", type: "action", defaultParams: { message: "Signal triggered" } },
  ],
};

const TYPE_COLORS = {
  trigger: "border-l-blue-500 text-blue-400",
  condition: "border-l-yellow-500 text-yellow-400",
  action: "border-l-green-500 text-green-400",
};

interface PaletteProps {
  onAddNode: (node: Omit<StrategyNode, "id" | "x" | "y">) => void;
}

export default function NodePalette({ onAddNode }: PaletteProps) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    Triggers: true,
    Conditions: true,
    Actions: true,
  });

  const toggle = (group: string) => {
    setExpanded((prev) => ({ ...prev, [group]: !prev[group] }));
  };

  return (
    <div className="space-y-2">
      {Object.entries(NODE_DEFS).map(([group, defs]) => (
        <div key={group}>
          <button
            onClick={() => toggle(group)}
            className="flex items-center gap-1 text-xs font-medium text-gray-400 hover:text-white w-full py-1"
          >
            {expanded[group] ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            {group}
          </button>
          {expanded[group] && (
            <div className="space-y-1 ml-1">
              {defs.map((def) => (
                <button
                  key={def.name}
                  onClick={() =>
                    onAddNode({
                      type: def.type,
                      name: def.name,
                      category: def.category,
                      params: { ...def.defaultParams },
                    })
                  }
                  className={cn(
                    "w-full text-left border-l-2 rounded-r px-2 py-1.5 text-[10px] bg-gray-800/50 hover:bg-gray-800 transition-colors",
                    TYPE_COLORS[def.type]
                  )}
                >
                  <span className="font-medium text-white block">{def.name}</span>
                  <span className="text-gray-500">{def.category}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
