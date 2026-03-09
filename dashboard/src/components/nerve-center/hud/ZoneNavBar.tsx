"use client";

import { useNerveCenterStore } from "../NerveCenterStore";
import { ZONES, type ZoneId } from "../zones/ZoneConfig";

const allZones = [
  { id: "overview" as const, name: "Overview", icon: "🌍", keyboard: "0" },
  ...ZONES.map((z) => ({ id: z.id as ZoneId, name: z.name, icon: z.icon, keyboard: z.keyboard })),
];

export default function ZoneNavBar() {
  const activeZone = useNerveCenterStore((s) => s.activeZone);
  const nearestZone = useNerveCenterStore((s) => s.nearestZone);
  const setActiveZone = useNerveCenterStore((s) => s.setActiveZone);

  return (
    <div className="absolute bottom-4 left-1/2 -translate-x-1/2 pointer-events-auto">
      <div className="flex gap-1 bg-gray-950/90 backdrop-blur-md border border-amber-700/30 rounded-xl px-2 py-1.5 shadow-2xl">
        {allZones.map((zone) => {
          const isNear = nearestZone === zone.id;
          const isActive = activeZone === zone.id;
          return (
            <button
              key={zone.id}
              onClick={() => setActiveZone(zone.id)}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-bold transition-all ${
                isNear
                  ? "bg-amber-600/30 text-amber-200 border border-amber-400/50 shadow-lg shadow-amber-500/10"
                  : isActive
                    ? "bg-amber-600/15 text-amber-300 border border-amber-500/30"
                    : "text-gray-400 hover:text-white hover:bg-gray-800/50 border border-transparent"
              }`}
            >
              <span className="text-sm">{zone.icon}</span>
              <span className="hidden sm:inline">{zone.name}</span>
              {isNear && <span className="text-[8px] text-amber-400 hidden sm:inline">(here)</span>}
              <kbd className="hidden md:inline text-[8px] text-gray-600 bg-gray-800 rounded px-1 py-0.5 ml-0.5">{zone.keyboard}</kbd>
            </button>
          );
        })}
      </div>
    </div>
  );
}
