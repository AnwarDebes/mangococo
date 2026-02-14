"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import { getSystemHealth } from "@/lib/api";
import { getTimeSince, cn } from "@/lib/utils";
import type { SystemHealth as SystemHealthType } from "@/types";

export default function SystemHealth() {
  const { data: services, isLoading } = useQuery({
    queryKey: ["health"],
    queryFn: getSystemHealth,
    refetchInterval: 10000,
  });

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="card animate-pulse">
            <div className="h-4 w-20 rounded bg-gray-700" />
            <div className="mt-2 h-3 w-12 rounded bg-gray-700" />
          </div>
        ))}
      </div>
    );
  }

  if (!services || services.length === 0) {
    return (
      <div className="card text-center text-sm text-gray-500">
        <Activity size={20} className="mx-auto mb-2 text-gray-600" />
        No services reporting
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {services.map((svc: SystemHealthType) => {
        const uptimeHours = Math.floor(svc.uptime / 3600);
        const uptimeMinutes = Math.floor((svc.uptime % 3600) / 60);
        return (
          <div key={svc.service_name} className="card-hover">
            <div className="flex items-center gap-2">
              <div
                className={cn(
                  "status-dot",
                  svc.status === "healthy"
                    ? "status-healthy"
                    : svc.status === "degraded"
                    ? "status-degraded"
                    : "status-down"
                )}
              />
              <span className="text-sm font-medium text-white truncate">
                {svc.service_name}
              </span>
            </div>
            <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
              <span>
                {uptimeHours}h {uptimeMinutes}m
              </span>
              <span>{getTimeSince(svc.last_heartbeat)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
