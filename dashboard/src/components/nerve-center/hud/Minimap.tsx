"use client";

import { useEffect, useState } from "react";
import { useNerveCenterStore } from "../NerveCenterStore";
import { ZONES, ZONE_CONNECTIONS } from "../zones/ZoneConfig";

export default function Minimap() {
  const activeZone = useNerveCenterStore((s) => s.activeZone);
  const setActiveZone = useNerveCenterStore((s) => s.setActiveZone);
  const showMinimap = useNerveCenterStore((s) => s.showMinimap);
  const toggleMinimap = useNerveCenterStore((s) => s.toggleMinimap);
  const [playerPos, setPlayerPos] = useState<[number, number]>([0, 30]);

  // Poll player position from store
  useEffect(() => {
    const interval = setInterval(() => {
      const wp = useNerveCenterStore.getState().cameraWorldPos;
      setPlayerPos([wp[0], wp[2]]);
    }, 150);
    return () => clearInterval(interval);
  }, []);

  if (!showMinimap) {
    return (
      <button onClick={toggleMinimap} className="absolute top-3 right-3 pointer-events-auto bg-gray-950/80 backdrop-blur border border-gray-700/50 rounded-lg px-2 py-1 text-[10px] text-gray-400 hover:text-white">
        Map
      </button>
    );
  }

  const scale = 2.2;
  const toSvg = (x: number, z: number) => ({ x: x * scale, y: z * scale });

  return (
    <div className="absolute top-3 right-3 pointer-events-auto">
      <div className="bg-gray-950/90 backdrop-blur-md border border-amber-700/30 rounded-xl p-2 shadow-2xl">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[9px] text-amber-400 font-bold uppercase tracking-wider">Kingdom Map</span>
          <button onClick={toggleMinimap} className="text-gray-500 hover:text-white text-xs">x</button>
        </div>
        <svg viewBox="-60 -75 120 145" className="w-44 h-48">
          {/* Flow connections */}
          {ZONE_CONNECTIONS.map((conn, i) => {
            const from = ZONES.find((z) => z.id === conn.from);
            const to = ZONES.find((z) => z.id === conn.to);
            if (!from || !to) return null;
            const f = toSvg(from.position[0], from.position[2]);
            const t = toSvg(to.position[0], to.position[2]);
            return (
              <line key={i} x1={f.x} y1={f.y} x2={t.x} y2={t.y} stroke={conn.color} strokeWidth={0.6} opacity={0.2} strokeDasharray="3 2" />
            );
          })}

          {/* Roads from center to each zone */}
          {ZONES.filter((z) => z.id !== "treasury").map((zone) => {
            const p = toSvg(zone.position[0], zone.position[2]);
            return (
              <line key={`road-${zone.id}`} x1={0} y1={0} x2={p.x} y2={p.y} stroke={zone.glowColor} strokeWidth={1} opacity={0.08} />
            );
          })}

          {/* Zone dots */}
          {ZONES.map((zone) => {
            const pos = toSvg(zone.position[0], zone.position[2]);
            const isActive = activeZone === zone.id;
            return (
              <g key={zone.id} onClick={() => setActiveZone(zone.id)} className="cursor-pointer">
                {isActive && <circle cx={pos.x} cy={pos.y} r={8} fill="none" stroke={zone.glowColor} strokeWidth={1} opacity={0.5} />}
                <circle cx={pos.x} cy={pos.y} r={4} fill={zone.glowColor} opacity={isActive ? 1 : 0.5} />
                <text x={pos.x} y={pos.y + 9} textAnchor="middle" fill={zone.glowColor} fontSize={5} fontWeight="bold" opacity={0.8}>
                  {zone.name}
                </text>
              </g>
            );
          })}

          {/* Player position (golden pulsing dot) */}
          <g>
            <circle cx={playerPos[0] * scale} cy={playerPos[1] * scale} r={3} fill="#fbbf24" opacity={0.95}>
              <animate attributeName="r" values="2;4;2" dur="1.2s" repeatCount="indefinite" />
            </circle>
            <circle cx={playerPos[0] * scale} cy={playerPos[1] * scale} r={6} fill="none" stroke="#fbbf24" strokeWidth={0.5} opacity={0.4}>
              <animate attributeName="r" values="4;7;4" dur="1.2s" repeatCount="indefinite" />
            </circle>
            <text x={playerPos[0] * scale} y={playerPos[1] * scale - 6} textAnchor="middle" fill="#fbbf24" fontSize={5} fontWeight="bold" opacity={0.7}>
              YOU
            </text>
          </g>
        </svg>
      </div>
    </div>
  );
}
