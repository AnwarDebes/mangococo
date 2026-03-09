"use client";

import { useNerveCenterStore } from "../NerveCenterStore";
import { useNerveCenterData } from "@/hooks/useNerveCenterData";
import TreasuryDetail from "./details/TreasuryDetail";
import WarRoomDetail from "./details/WarRoomDetail";
import OracleDetail from "./details/OracleDetail";
import WizardDetail from "./details/WizardDetail";
import GuardDetail from "./details/GuardDetail";
import MarketDetail from "./details/MarketDetail";
import { ZONES } from "../zones/ZoneConfig";

export default function ZoneDetailPanel() {
  const nearestZone = useNerveCenterStore((s) => s.nearestZone);
  const data = useNerveCenterData();

  if (!nearestZone) return null;

  const zoneDef = ZONES.find((z) => z.id === nearestZone);
  if (!zoneDef) return null;

  return (
    <div className="absolute top-16 right-48 w-72 pointer-events-auto max-h-[70vh] overflow-y-auto">
      <div className="bg-gray-950/90 backdrop-blur-md border rounded-xl overflow-hidden shadow-2xl" style={{ borderColor: `${zoneDef.glowColor}40` }}>
        {/* Zone header */}
        <div className="px-3 py-2 bg-gradient-to-r from-gray-900/50 to-transparent border-b" style={{ borderColor: `${zoneDef.glowColor}20` }}>
          <div className="flex items-center gap-2">
            <span className="text-lg">{zoneDef.icon}</span>
            <div>
              <div className="text-xs font-bold" style={{ color: zoneDef.glowColor }}>{zoneDef.rpgTitle}</div>
              <div className="text-[9px] text-gray-500 italic">Zone Details</div>
            </div>
          </div>
        </div>

        {/* Zone content */}
        <div className="p-3">
          {nearestZone === "treasury" && <TreasuryDetail portfolio={data.portfolio} positions={data.positions} />}
          {nearestZone === "warRoom" && <WarRoomDetail positions={data.positions} />}
          {nearestZone === "oracleTower" && <OracleDetail signals={data.signals} />}
          {nearestZone === "wizardAcademy" && <WizardDetail models={data.models} />}
          {nearestZone === "guardTower" && <GuardDetail positions={data.positions} health={data.health} />}
          {nearestZone === "marketSquare" && <MarketDetail tickers={data.tickers} fearGreed={data.fearGreed} globalMarket={data.globalMarket} />}
        </div>
      </div>
    </div>
  );
}
