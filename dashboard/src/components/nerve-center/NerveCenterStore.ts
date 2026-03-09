import { create } from "zustand";
import { ZONES, OVERVIEW_PRESET, getZoneById } from "./zones/ZoneConfig";
import type { ZoneId } from "./zones/ZoneConfig";

export interface KingdomEvent {
  id: string;
  timestamp: number;
  type: "signal" | "trade" | "health" | "model" | "market" | "risk";
  message: string;
  icon: string;
  color: string;
}

interface NerveCenterState {
  // Zone navigation
  activeZone: ZoneId | "overview";
  setActiveZone: (zone: ZoneId | "overview") => void;
  nearestZone: ZoneId | null;
  setNearestZone: (zone: ZoneId | null) => void;

  // Player (GTA-style)
  playerPosition: [number, number, number];
  playerRotation: number; // Y-axis rotation (radians)
  setPlayerPosition: (pos: [number, number, number]) => void;
  setPlayerRotation: (rot: number) => void;
  isPlaying: boolean; // pointer lock active
  setIsPlaying: (v: boolean) => void;
  walkToTarget: [number, number, number] | null; // auto-walk destination
  setWalkToTarget: (target: [number, number, number] | null) => void;

  // Camera
  isAnimating: boolean;
  setIsAnimating: (v: boolean) => void;
  cameraTarget: [number, number, number] | null;
  cameraLookAt: [number, number, number] | null;
  cameraWorldPos: [number, number, number];
  cameraAngleH: number; // horizontal orbit angle around player
  cameraAngleV: number; // vertical angle (pitch)
  setCameraAngleH: (a: number) => void;
  setCameraAngleV: (a: number) => void;
  flyTo: (pos: [number, number, number] | null, lookAt?: [number, number, number] | null) => void;

  // Selected objects
  selectedNode: string | null;
  selectNode: (id: string | null) => void;
  selectedSignalId: string | null;
  selectSignal: (id: string | null) => void;
  selectedPositionSymbol: string | null;
  selectPosition: (symbol: string | null) => void;

  // Filters
  signalFilter: "ALL" | "BUY" | "SELL" | "HOLD";
  setSignalFilter: (f: "ALL" | "BUY" | "SELL" | "HOLD") => void;

  // Performance
  particleCount: "low" | "medium" | "high";
  setParticleCount: (level: "low" | "medium" | "high") => void;

  // Event feed
  eventFeed: KingdomEvent[];
  addEvent: (event: KingdomEvent) => void;
  showEventFeed: boolean;
  toggleEventFeed: () => void;

  // Minimap
  showMinimap: boolean;
  toggleMinimap: () => void;

  // Data refresh
  lastRefresh: number;
  triggerRefresh: () => void;
}

export const useNerveCenterStore = create<NerveCenterState>((set, get) => ({
  // Zone navigation
  activeZone: "overview",
  setActiveZone: (zone) => {
    if (zone === "overview") {
      // Auto-walk player back to center
      set({ activeZone: "overview", walkToTarget: [0, 0, 25] });
    } else {
      const def = getZoneById(zone);
      if (def) {
        // Auto-walk to zone position (offset slightly so player faces the zone)
        const zp = def.position;
        // Stand ~6 units away from zone center, toward the center of the kingdom
        const dx = -zp[0];
        const dz = -zp[2];
        const len = Math.sqrt(dx * dx + dz * dz) || 1;
        const standX = zp[0] + (dx / len) * 6;
        const standZ = zp[2] + (dz / len) * 6;
        set({
          activeZone: zone,
          walkToTarget: [standX, 0, standZ],
        });
      }
    }
  },
  nearestZone: null,
  setNearestZone: (zone) => {
    if (get().nearestZone !== zone) set({ nearestZone: zone });
  },

  // Player
  playerPosition: [0, 0, 30],
  playerRotation: 0,
  setPlayerPosition: (pos) => set({ playerPosition: pos }),
  setPlayerRotation: (rot) => set({ playerRotation: rot }),
  isPlaying: false,
  setIsPlaying: (v) => set({ isPlaying: v }),
  walkToTarget: null,
  setWalkToTarget: (target) => set({ walkToTarget: target }),

  // Camera
  isAnimating: false,
  setIsAnimating: (v) => set({ isAnimating: v }),
  cameraTarget: null,
  cameraLookAt: null,
  cameraWorldPos: [0, 10, 35],
  cameraAngleH: 0,
  cameraAngleV: 0.3,
  setCameraAngleH: (a) => set({ cameraAngleH: a }),
  setCameraAngleV: (a) => set({ cameraAngleV: a }),
  flyTo: (pos, lookAt) =>
    set({ cameraTarget: pos, cameraLookAt: lookAt ?? null, isAnimating: true }),

  // Selected objects
  selectedNode: null,
  selectNode: (id) => set({ selectedNode: id }),
  selectedSignalId: null,
  selectSignal: (id) => set({ selectedSignalId: id }),
  selectedPositionSymbol: null,
  selectPosition: (symbol) => set({ selectedPositionSymbol: symbol }),

  // Filters
  signalFilter: "ALL",
  setSignalFilter: (f) => set({ signalFilter: f }),

  // Performance
  particleCount: "medium",
  setParticleCount: (level) => set({ particleCount: level }),

  // Event feed
  eventFeed: [],
  addEvent: (event) =>
    set((s) => ({ eventFeed: [event, ...s.eventFeed].slice(0, 50) })),
  showEventFeed: true,
  toggleEventFeed: () => set((s) => ({ showEventFeed: !s.showEventFeed })),

  // Minimap
  showMinimap: true,
  toggleMinimap: () => set((s) => ({ showMinimap: !s.showMinimap })),

  // Data refresh
  lastRefresh: Date.now(),
  triggerRefresh: () => set({ lastRefresh: Date.now() }),
}));
