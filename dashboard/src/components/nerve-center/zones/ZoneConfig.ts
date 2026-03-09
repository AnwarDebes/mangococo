export type ZoneId = "treasury" | "warRoom" | "oracleTower" | "wizardAcademy" | "guardTower" | "marketSquare";

export interface ZoneDefinition {
  id: ZoneId;
  name: string;
  rpgTitle: string;
  icon: string;
  position: [number, number, number];
  cameraPosition: [number, number, number];
  cameraLookAt: [number, number, number];
  proximityRadius: number;
  lightColor: string;
  keyboard: string;
  islandRadius: number;
  islandColor: string;
  glowColor: string;
}

/**
 * Symmetric pentagon layout — 5 outer zones at equal spacing (R=20, 72° apart)
 * around a center Treasury. Player spawns south looking north.
 *
 *              Oracle(12,16)     Wizard(-12,16)
 *                    \             /
 *          Market(19,-6)  Treasury(0,0)  Guard(-19,-6)
 *                       \   |   /
 *                      WarRoom(0,-20)
 */
export const ZONES: ZoneDefinition[] = [
  {
    id: "treasury",
    name: "Treasury",
    rpgTitle: "The Royal Treasury",
    icon: "👑",
    position: [0, 0, 0],
    cameraPosition: [0, 8, 14],
    cameraLookAt: [0, 1, 0],
    proximityRadius: 12,
    lightColor: "#fbbf24",
    keyboard: "1",
    islandRadius: 6,
    islandColor: "#1c1917",
    glowColor: "#f59e0b",
  },
  {
    id: "warRoom",
    name: "War Room",
    rpgTitle: "The Battle Arena",
    icon: "⚔",
    position: [0, 0, -20],
    cameraPosition: [0, 6, -10],
    cameraLookAt: [0, 0, -20],
    proximityRadius: 12,
    lightColor: "#22c55e",
    keyboard: "2",
    islandRadius: 6,
    islandColor: "#14532d",
    glowColor: "#22c55e",
  },
  {
    id: "marketSquare",
    name: "Market Square",
    rpgTitle: "The Grand Bazaar",
    icon: "📊",
    position: [19, 0, -6],
    cameraPosition: [27, 8, 1],
    cameraLookAt: [19, 1, -6],
    proximityRadius: 12,
    lightColor: "#3b82f6",
    keyboard: "3",
    islandRadius: 5,
    islandColor: "#0c2240",
    glowColor: "#3b82f6",
  },
  {
    id: "oracleTower",
    name: "Oracle Tower",
    rpgTitle: "The Oracle's Sanctum",
    icon: "🔮",
    position: [12, 0, 16],
    cameraPosition: [20, 8, 23],
    cameraLookAt: [12, 1, 16],
    proximityRadius: 12,
    lightColor: "#06b6d4",
    keyboard: "4",
    islandRadius: 5,
    islandColor: "#164e63",
    glowColor: "#06b6d4",
  },
  {
    id: "wizardAcademy",
    name: "Wizard Academy",
    rpgTitle: "The Arcane Academy",
    icon: "🧙",
    position: [-12, 0, 16],
    cameraPosition: [-20, 8, 23],
    cameraLookAt: [-12, 1, 16],
    proximityRadius: 12,
    lightColor: "#a78bfa",
    keyboard: "5",
    islandRadius: 5,
    islandColor: "#1e1b4b",
    glowColor: "#a78bfa",
  },
  {
    id: "guardTower",
    name: "Guard Tower",
    rpgTitle: "The Sentinel's Watch",
    icon: "🛡",
    position: [-19, 0, -6],
    cameraPosition: [-27, 8, 1],
    cameraLookAt: [-19, 1, -6],
    proximityRadius: 12,
    lightColor: "#ef4444",
    keyboard: "6",
    islandRadius: 5,
    islandColor: "#450a0a",
    glowColor: "#ef4444",
  },
];

export const OVERVIEW_PRESET = {
  cameraPosition: [0, 30, 45] as [number, number, number],
  cameraLookAt: [0, 0, 0] as [number, number, number],
};

export function getZoneById(id: ZoneId): ZoneDefinition | undefined {
  return ZONES.find((z) => z.id === id);
}

/** Data flow connections between zones (for DataFlowLines + minimap) */
export const ZONE_CONNECTIONS: Array<{
  from: ZoneId;
  to: ZoneId;
  color: string;
  label: string;
}> = [
  { from: "marketSquare", to: "oracleTower", color: "#3b82f6", label: "Market Data" },
  { from: "oracleTower", to: "treasury", color: "#06b6d4", label: "Signals" },
  { from: "oracleTower", to: "warRoom", color: "#22c55e", label: "Trade Orders" },
  { from: "guardTower", to: "treasury", color: "#ef4444", label: "Risk Watch" },
  { from: "wizardAcademy", to: "oracleTower", color: "#a78bfa", label: "Predictions" },
  { from: "treasury", to: "guardTower", color: "#f59e0b", label: "Position Data" },
];
