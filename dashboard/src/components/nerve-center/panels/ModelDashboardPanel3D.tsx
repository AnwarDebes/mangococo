"use client";

import { Html } from "@react-three/drei";
import type { ModelStatus } from "@/types";

interface ModelDashboardPanel3DProps {
  models: ModelStatus[];
  position: [number, number, number];
}

export default function ModelDashboardPanel3D({ models, position }: ModelDashboardPanel3DProps) {
  if (!models.length) return null;

  const avgAccuracy = models.reduce((sum, m) => sum + m.accuracy, 0) / models.length;

  return (
    <Html position={position} distanceFactor={12} style={{ pointerEvents: "none" }}>
      <div className="bg-gray-900/90 border border-purple-500/20 rounded-lg p-3 w-60 backdrop-blur select-none">
        <div className="text-xs font-bold text-purple-400 mb-2">AI Models</div>
        <div className="space-y-2">
          {models.map((model) => {
            const statusColor =
              model.status === "active" ? "#22c55e" :
              model.status === "training" ? "#f59e0b" : "#6b7280";
            return (
              <div key={model.model_name}>
                <div className="flex items-center justify-between text-[11px] mb-0.5">
                  <div className="flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: statusColor }} />
                    <span className="text-gray-300 font-medium">{model.model_name}</span>
                  </div>
                  <span className="text-gray-400 text-[10px]">{model.status}</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="flex-1 bg-gray-700 rounded-full h-1.5">
                    <div
                      className="h-1.5 rounded-full"
                      style={{
                        width: `${model.accuracy * 100}%`,
                        backgroundColor: statusColor,
                      }}
                    />
                  </div>
                  <span className="text-[10px] text-gray-400 w-10 text-right">
                    {(model.accuracy * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            );
          })}
        </div>
        <div className="mt-2 pt-2 border-t border-gray-700 flex justify-between text-[10px]">
          <span className="text-gray-500">Avg Accuracy</span>
          <span className="text-white font-medium">{(avgAccuracy * 100).toFixed(1)}%</span>
        </div>
      </div>
    </Html>
  );
}
