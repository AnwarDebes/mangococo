"use client";

import { useQuery } from "@tanstack/react-query";
import { getSystemHealth, getModelStatus } from "@/lib/api";
import { getTimeSince, cn } from "@/lib/utils";
import SystemHealth from "@/components/panels/SystemHealth";
import type { ModelStatus } from "@/types";

export default function SystemPage() {
  const { data: models, isLoading: loadingModels } = useQuery({
    queryKey: ["models"],
    queryFn: getModelStatus,
    refetchInterval: 30000,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">System Status</h1>
        <p className="text-sm text-gray-400">
          Service health and model monitoring
        </p>
      </div>

      {/* Service Health */}
      <div>
        <h2 className="mb-3 text-lg font-semibold text-white">
          Service Health Matrix
        </h2>
        <SystemHealth />
      </div>

      {/* Model Status */}
      <div>
        <h2 className="mb-3 text-lg font-semibold text-white">
          AI Model Status
        </h2>
        {loadingModels ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="card animate-pulse h-32" />
            ))}
          </div>
        ) : !models || models.length === 0 ? (
          <div className="card text-center text-sm text-gray-500 py-8">
            No models reporting
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {models.map((model: ModelStatus) => (
              <div key={model.model_name} className="card-hover">
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-white">
                    {model.model_name}
                  </h3>
                  <span
                    className={cn(
                      "badge",
                      model.status === "active"
                        ? "bg-green-500/20 text-green-400"
                        : model.status === "training"
                        ? "bg-yellow-500/20 text-yellow-400"
                        : "bg-gray-500/20 text-gray-400"
                    )}
                  >
                    {model.status}
                  </span>
                </div>
                <div className="mt-3 space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-500">Version</span>
                    <span className="font-mono text-gray-300">
                      {model.version}
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-500">Accuracy</span>
                    <span
                      className={cn(
                        "font-mono font-medium",
                        model.accuracy >= 0.7
                          ? "text-profit"
                          : model.accuracy >= 0.5
                          ? "text-mango-500"
                          : "text-loss"
                      )}
                    >
                      {(model.accuracy * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-500">Last Retrain</span>
                    <span className="text-gray-400">
                      {getTimeSince(model.last_retrain)}
                    </span>
                  </div>
                </div>
                {/* Accuracy bar */}
                <div className="mt-3 h-1.5 rounded-full bg-gray-700">
                  <div
                    className={cn(
                      "h-1.5 rounded-full transition-all",
                      model.accuracy >= 0.7
                        ? "bg-green-500"
                        : model.accuracy >= 0.5
                        ? "bg-mango-500"
                        : "bg-red-500"
                    )}
                    style={{ width: `${model.accuracy * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
