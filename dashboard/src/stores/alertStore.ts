import { create } from "zustand";

export type AlertCondition =
  | { type: "price_above"; symbol: string; value: number }
  | { type: "price_below"; symbol: string; value: number }
  | { type: "fear_greed_above"; value: number }
  | { type: "fear_greed_below"; value: number }
  | { type: "funding_rate_extreme"; symbol: string; threshold: number }
  | { type: "volume_spike"; symbol: string; multiplier: number }
  | { type: "correlation_break"; pair: [string, string]; threshold: number };

export interface Alert {
  id: string;
  name: string;
  condition: AlertCondition;
  enabled: boolean;
  triggered: boolean;
  lastTriggered: string | null;
  createdAt: string;
}

interface AlertState {
  alerts: Alert[];
  addAlert: (name: string, condition: AlertCondition) => void;
  removeAlert: (id: string) => void;
  toggleAlert: (id: string) => void;
  markTriggered: (id: string) => void;
  resetAlert: (id: string) => void;
}

function loadAlerts(): Alert[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem("goblin-alerts");
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveAlerts(alerts: Alert[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem("goblin-alerts", JSON.stringify(alerts));
  } catch {}
}

let idCounter = 0;

export const useAlertStore = create<AlertState>((set, get) => ({
  alerts: loadAlerts(),

  addAlert: (name, condition) => {
    const alerts = get().alerts;
    if (alerts.length >= 20) return;
    const newAlert: Alert = {
      id: `alert-${Date.now()}-${++idCounter}`,
      name,
      condition,
      enabled: true,
      triggered: false,
      lastTriggered: null,
      createdAt: new Date().toISOString(),
    };
    const updated = [...alerts, newAlert];
    saveAlerts(updated);
    set({ alerts: updated });
  },

  removeAlert: (id) => {
    const updated = get().alerts.filter((a) => a.id !== id);
    saveAlerts(updated);
    set({ alerts: updated });
  },

  toggleAlert: (id) => {
    const updated = get().alerts.map((a) =>
      a.id === id ? { ...a, enabled: !a.enabled } : a
    );
    saveAlerts(updated);
    set({ alerts: updated });
  },

  markTriggered: (id) => {
    const updated = get().alerts.map((a) =>
      a.id === id ? { ...a, triggered: true, lastTriggered: new Date().toISOString() } : a
    );
    saveAlerts(updated);
    set({ alerts: updated });
  },

  resetAlert: (id) => {
    const updated = get().alerts.map((a) =>
      a.id === id ? { ...a, triggered: false } : a
    );
    saveAlerts(updated);
    set({ alerts: updated });
  },
}));
