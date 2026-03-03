"use client";

import type { StrategyNode, StrategyConnection } from "@/types";

interface Template {
  name: string;
  description: string;
  nodes: Omit<StrategyNode, "id">[];
  connections: Array<[number, number]>; // indices into nodes array
}

const TEMPLATES: Template[] = [
  {
    name: "Conservative",
    description: "RSI < 30 AND Confidence > 0.7 → Buy 10% → Stop-Loss 2% → Take-Profit 3%",
    nodes: [
      { type: "trigger", name: "RSI Threshold", category: "RSI crosses below 30", params: { period: 14, threshold: 30, direction: "below" }, x: 50, y: 80 },
      { type: "condition", name: "Confidence Filter", category: "AI confidence > 0.7", params: { min_confidence: 0.7 }, x: 280, y: 50 },
      { type: "condition", name: "AND Gate", category: "All inputs required", params: {}, x: 280, y: 150 },
      { type: "action", name: "Buy", category: "Buy 10% of capital", params: { size_pct: 10, order_type: "market" }, x: 510, y: 50 },
      { type: "action", name: "Set Stop-Loss", category: "2% below entry", params: { percent: 2 }, x: 510, y: 150 },
      { type: "action", name: "Set Take-Profit", category: "3% above entry", params: { percent: 3 }, x: 510, y: 250 },
    ],
    connections: [[0, 2], [1, 2], [2, 3], [2, 4], [2, 5]],
  },
  {
    name: "Aggressive",
    description: "MACD Cross AND Volume Spike → Buy 25% → Stop-Loss 5% → Take-Profit 8%",
    nodes: [
      { type: "trigger", name: "MACD Cross", category: "MACD crosses signal", params: { fast: 12, slow: 26, signal: 9 }, x: 50, y: 50 },
      { type: "trigger", name: "Volume Spike", category: "Volume > 2x average", params: { multiplier: 2.0, period: 20 }, x: 50, y: 170 },
      { type: "condition", name: "AND Gate", category: "All inputs required", params: {}, x: 280, y: 110 },
      { type: "action", name: "Buy", category: "Buy 25% of capital", params: { size_pct: 25, order_type: "market" }, x: 510, y: 50 },
      { type: "action", name: "Set Stop-Loss", category: "5% below entry", params: { percent: 5 }, x: 510, y: 150 },
      { type: "action", name: "Set Take-Profit", category: "8% above entry", params: { percent: 8 }, x: 510, y: 250 },
    ],
    connections: [[0, 2], [1, 2], [2, 3], [2, 4], [2, 5]],
  },
  {
    name: "Sentiment Hunter",
    description: "Sentiment Shift (>10pts) AND Whale Alert (>$5M outflow) → Buy 15%",
    nodes: [
      { type: "trigger", name: "Sentiment Shift", category: "Sentiment changes > 10 pts", params: { threshold: 10 }, x: 50, y: 50 },
      { type: "trigger", name: "Whale Alert", category: "Whale tx > $5M", params: { min_usd: 5000000 }, x: 50, y: 170 },
      { type: "condition", name: "AND Gate", category: "All inputs required", params: {}, x: 280, y: 110 },
      { type: "action", name: "Buy", category: "Buy 15% of capital", params: { size_pct: 15, order_type: "market" }, x: 510, y: 110 },
    ],
    connections: [[0, 2], [1, 2], [2, 3]],
  },
];

interface TemplatesProps {
  onLoad: (nodes: StrategyNode[], connections: StrategyConnection[]) => void;
}

export default function StrategyTemplates({ onLoad }: TemplatesProps) {
  const handleLoad = (template: Template) => {
    const nodes: StrategyNode[] = template.nodes.map((n, i) => ({
      ...n,
      id: `node_${Date.now()}_${i}`,
    }));
    const connections: StrategyConnection[] = template.connections.map(([fromIdx, toIdx]) => ({
      id: `conn_${nodes[fromIdx].id}_${nodes[toIdx].id}`,
      from: nodes[fromIdx].id,
      to: nodes[toIdx].id,
    }));
    onLoad(nodes, connections);
  };

  return (
    <div className="space-y-2">
      <p className="text-xs text-gray-500 font-medium">Templates</p>
      {TEMPLATES.map((t) => (
        <button
          key={t.name}
          onClick={() => handleLoad(t)}
          className="w-full text-left p-2 rounded-lg bg-gray-800/50 border border-gray-700 hover:border-goblin-500/30 transition-colors"
        >
          <p className="text-xs font-bold text-white">{t.name}</p>
          <p className="text-[9px] text-gray-500 mt-0.5 leading-snug">{t.description}</p>
        </button>
      ))}
    </div>
  );
}
