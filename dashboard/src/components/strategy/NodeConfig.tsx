"use client";

import { cn } from "@/lib/utils";
import { Trash2 } from "lucide-react";
import type { StrategyNode } from "@/types";

interface NodeConfigProps {
  node: StrategyNode;
  onUpdate: (node: StrategyNode) => void;
  onDelete: (nodeId: string) => void;
}

export default function NodeConfig({ node, onUpdate, onDelete }: NodeConfigProps) {
  const handleParamChange = (key: string, value: string | number | boolean) => {
    onUpdate({
      ...node,
      params: { ...node.params, [key]: value },
    });
  };

  const handleNameChange = (name: string) => {
    onUpdate({ ...node, name });
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-bold text-white">Node Config</h4>
        <button
          onClick={() => onDelete(node.id)}
          className="text-gray-500 hover:text-red-400 transition-colors"
        >
          <Trash2 size={14} />
        </button>
      </div>

      {/* Node name */}
      <div>
        <label className="text-[10px] text-gray-500 block mb-0.5">Name</label>
        <input
          value={node.name}
          onChange={(e) => handleNameChange(e.target.value)}
          className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white"
        />
      </div>

      <div className="text-[10px] text-gray-500">
        Type: <span className={cn(
          "font-medium",
          node.type === "trigger" ? "text-blue-400" :
          node.type === "condition" ? "text-yellow-400" : "text-green-400"
        )}>{node.type}</span>
      </div>

      {/* Parameters */}
      {Object.entries(node.params).map(([key, value]) => (
        <div key={key}>
          <label className="text-[10px] text-gray-500 block mb-0.5 capitalize">
            {key.replace(/_/g, " ")}
          </label>
          {typeof value === "boolean" ? (
            <button
              onClick={() => handleParamChange(key, !value)}
              className={cn(
                "px-3 py-1 text-xs rounded border",
                value
                  ? "border-goblin-500/50 bg-goblin-500/10 text-goblin-400"
                  : "border-gray-700 bg-gray-800 text-gray-400"
              )}
            >
              {value ? "Enabled" : "Disabled"}
            </button>
          ) : typeof value === "number" ? (
            <input
              type="number"
              value={value}
              onChange={(e) => handleParamChange(key, Number(e.target.value))}
              className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white"
            />
          ) : (
            <input
              value={String(value)}
              onChange={(e) => handleParamChange(key, e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white"
            />
          )}
        </div>
      ))}
    </div>
  );
}
