"use client";

import type { ModelStatus } from "@/types";

interface Props {
  models: ModelStatus[];
}

export default function WizardDetail({ models }: Props) {
  const avgAcc = models.length > 0
    ? models.reduce((s, m) => s + m.accuracy, 0) / models.length
    : 0;
  const activeCount = models.filter((m) => m.status === "active").length;

  return (
    <div className="space-y-3">
      {/* Summary */}
      <div className="flex gap-2">
        <div className="flex-1 bg-purple-500/10 border border-purple-500/20 rounded-lg px-2 py-1.5 text-center">
          <div className="text-lg font-black text-purple-300">{(avgAcc * 100).toFixed(0)}%</div>
          <div className="text-[8px] text-gray-500 uppercase">Avg Power</div>
        </div>
        <div className="flex-1 bg-green-500/10 border border-green-500/20 rounded-lg px-2 py-1.5 text-center">
          <div className="text-lg font-black text-green-400">{activeCount}/{models.length}</div>
          <div className="text-[8px] text-gray-500 uppercase">Active</div>
        </div>
      </div>

      {/* Model cards */}
      <div className="space-y-1.5">
        {models.map((m) => {
          const acc = Math.round(m.accuracy * 100);
          return (
            <div key={m.model_name} className="bg-gray-900/50 rounded-lg px-2.5 py-2 border border-purple-800/30">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${
                    m.status === "active" ? "bg-green-500" : m.status === "training" ? "bg-purple-500 animate-pulse" : "bg-gray-600"
                  }`} />
                  <span className="text-xs font-bold text-white">{m.model_name}</span>
                </div>
                <span className="text-[9px] text-gray-500">v{m.version}</span>
              </div>
              <div className="flex items-center gap-1">
                <span className="text-[9px] text-purple-400 w-8">PWR</span>
                <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-purple-600 to-purple-400 transition-all"
                    style={{ width: `${acc}%` }}
                  />
                </div>
                <span className="text-[9px] text-purple-300 w-8 text-right">{acc}%</span>
              </div>
              <div className="text-[8px] text-gray-600 mt-0.5">
                Last trained: {new Date(m.last_retrain).toLocaleDateString()}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
