"use client";

import { Html } from "@react-three/drei";
import type { SystemHealth } from "@/types";

interface SystemHealthPanel3DProps {
  health: SystemHealth[];
  position: [number, number, number];
}

export default function SystemHealthPanel3D({ health, position }: SystemHealthPanel3DProps) {
  if (!health.length) return null;

  return (
    <Html position={position} distanceFactor={12} style={{ pointerEvents: "none" }}>
      <div className="bg-gray-900/90 border border-goblin-500/20 rounded-lg p-3 w-56 backdrop-blur select-none">
        <div className="text-xs font-bold text-goblin-400 mb-2 flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-goblin-500 animate-pulse" />
          System Health
        </div>
        <div className="space-y-1.5">
          {health.map((service) => {
            const statusColor =
              service.status === "healthy" ? "#22c55e" :
              service.status === "degraded" ? "#f59e0b" : "#ef4444";
            const uptimeHrs = Math.floor(service.uptime / 3600);
            return (
              <div key={service.service_name} className="flex items-center justify-between text-[11px]">
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: statusColor }} />
                  <span className="text-gray-300">{service.service_name}</span>
                </div>
                <span className="text-gray-500">{uptimeHrs > 0 ? `${uptimeHrs}h` : "< 1h"}</span>
              </div>
            );
          })}
        </div>
      </div>
    </Html>
  );
}
