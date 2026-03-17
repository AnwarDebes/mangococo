"use client";

import { useEffect, useState, useRef } from "react";
import { usePathname } from "next/navigation";
import { Wifi, WifiOff, Bell, Volume2, VolumeX, Shield, Search } from "lucide-react";
import { useSSE } from "@/hooks/useSSE";
import { useNotificationStore } from "@/stores/notificationStore";
import { API_BASE } from "@/lib/api";
import EmergencyPanel from "@/components/panels/EmergencyPanel";
import PriceTicker from "@/components/panels/PriceTicker";
import AlertManager from "@/components/alerts/AlertManager";

const PAGE_NAMES: Record<string, string> = {
  "/": "Dashboard",
  "/nerve-center": "Nerve Center",
  "/war-room": "War Room",
  "/trading": "Live Trading",
  "/analytics": "Analytics",
  "/backtesting": "Backtesting Lab",
  "/strategy": "Strategy Builder",
  "/replay": "Market Replay",
  "/market": "Market Intelligence",
  "/derivatives": "Derivatives Intelligence",
  "/sentiment": "Sentiment",
  "/goblin-shop": "Goblin Grand Bazaar",
  "/goblin-coin": "GBLN Coin",
  "/system": "System Analyzer",
  "/logs": "AI Activity Logs",
};

export default function Header() {
  const { isConnected } = useSSE(`${API_BASE}/api/stream`);
  const [currentTime, setCurrentTime] = useState("");
  const pathname = usePathname();
  const [soundEnabled, setSoundEnabled] = useState(false);
  const [showNotifications, setShowNotifications] = useState(false);
  const [showEmergency, setShowEmergency] = useState(false);
  const notifRef = useRef<HTMLDivElement>(null);
  const emergencyRef = useRef<HTMLDivElement>(null);

  const { notifications, unreadCount, markAllRead, clearAll } = useNotificationStore();

  const pageName = PAGE_NAMES[pathname] || "Dashboard";

  useEffect(() => {
    const update = () =>
      setCurrentTime(
        new Date().toLocaleTimeString("en-US", {
          hour12: false,
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      );
    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, []);

  // Close dropdowns on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) {
        setShowNotifications(false);
      }
      if (emergencyRef.current && !emergencyRef.current.contains(e.target as Node)) {
        setShowEmergency(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Toggle sound with keyboard shortcut
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "s" && !e.ctrlKey && !e.metaKey && !(e.target instanceof HTMLInputElement) && !(e.target instanceof HTMLTextAreaElement)) {
        setSoundEnabled((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const openCommandPalette = () => {
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true }));
  };

  return (
    <>
      <header className="relative flex h-12 sm:h-16 items-center justify-between border-b border-gray-800/50 bg-gray-950/95 backdrop-blur-sm px-2 sm:px-6 overflow-hidden">
        {/* Subtle bottom accent line */}
        <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-goblin-500/20 to-transparent" />

        {/* CRT scanning line — hidden on mobile for performance */}
        <div className="header-scan-line hidden sm:block" />

        {/* Current page name */}
        <div className="hidden lg:flex items-center gap-2">
          <span className="text-sm font-semibold text-white">{pageName}</span>
        </div>

        {/* Spacer for mobile sidebar toggle button */}
        <div className="lg:hidden w-10 shrink-0" />

        <div className="flex items-center gap-1.5 sm:gap-3 ml-auto">
          {/* Search / Command Palette trigger */}
          <button
            onClick={openCommandPalette}
            className="hidden lg:flex items-center gap-2 rounded-lg border border-gray-700/50 bg-gray-800/50 px-3 py-1.5 text-xs text-gray-400 hover:border-goblin-500/30 hover:text-gray-300 transition-colors"
          >
            <Search size={14} />
            <span>Search...</span>
            <kbd className="rounded border border-gray-700 bg-gray-900 px-1.5 py-0.5 text-[10px] font-mono text-gray-500">Ctrl+K</kbd>
          </button>

          {/* Live market indicator */}
          <div className="hidden xl:flex items-center gap-2 text-xs text-gray-500">
            <div className="h-1 w-1 rounded-full bg-goblin-500 animate-pulse" />
            <span>Markets Open</span>
          </div>

          <div className="h-4 w-px bg-gray-800 hidden xl:block" />

          {/* Sound toggle — hidden on small mobile */}
          <button
            onClick={() => setSoundEnabled(!soundEnabled)}
            className="hidden sm:block text-gray-400 hover:text-white transition-colors"
            title={soundEnabled ? "Mute sounds" : "Enable sounds"}
          >
            {soundEnabled ? <Volume2 size={16} className="text-goblin-500" /> : <VolumeX size={16} />}
          </button>

          {/* Smart Alerts — hidden on small mobile */}
          <div className="relative hidden sm:block">
            <AlertManager />
          </div>

          {/* Notification bell */}
          <div ref={notifRef} className="relative">
            <button
              onClick={() => {
                setShowNotifications(!showNotifications);
                if (!showNotifications) markAllRead();
              }}
              className="relative text-gray-400 hover:text-white transition-colors"
            >
              <Bell size={16} />
              {unreadCount > 0 && (
                <span className="absolute -top-1.5 -right-1.5 h-4 w-4 rounded-full bg-red-500 text-[10px] font-bold text-white flex items-center justify-center">
                  {unreadCount > 9 ? "9+" : unreadCount}
                </span>
              )}
            </button>

            {/* Notification dropdown */}
            {showNotifications && (
              <div className="absolute right-0 top-full mt-2 w-[calc(100vw-2rem)] sm:w-80 max-w-80 max-h-[70vh] sm:max-h-96 overflow-y-auto rounded-xl border border-gray-700 bg-gray-900/95 backdrop-blur-xl shadow-2xl z-[200]">
                <div className="flex items-center justify-between border-b border-gray-800 px-4 py-2.5">
                  <span className="text-xs font-semibold text-white">Notifications</span>
                  <div className="flex gap-2">
                    <button onClick={markAllRead} className="text-[10px] text-gray-500 hover:text-goblin-400">Mark Read</button>
                    <button onClick={clearAll} className="text-[10px] text-gray-500 hover:text-red-400">Clear All</button>
                  </div>
                </div>
                <div className="divide-y divide-gray-800/50">
                  {notifications.length === 0 ? (
                    <div className="px-4 py-8 text-center text-xs text-gray-600">No notifications yet</div>
                  ) : (
                    notifications.slice(0, 20).map((n) => (
                      <div key={n.id} className="px-4 py-2.5 hover:bg-gray-800/50 transition-colors">
                        <p className="text-xs text-gray-300">{n.message}</p>
                        <p className="text-[10px] text-gray-600 mt-0.5">
                          {new Date(n.timestamp).toLocaleTimeString()}
                        </p>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Emergency panel */}
          <div ref={emergencyRef} className="relative">
            <button
              onClick={() => setShowEmergency(!showEmergency)}
              className="text-gray-400 hover:text-white transition-colors"
              title="Emergency Controls"
            >
              <Shield size={16} />
            </button>
            {showEmergency && (
              <div className="absolute right-0 top-full mt-2 z-[200]">
                <EmergencyPanel onClose={() => setShowEmergency(false)} />
              </div>
            )}
          </div>

          <div className="h-4 w-px bg-gray-800 hidden sm:block" />

          <span className="hidden sm:inline text-sm font-mono text-gray-400">{currentTime}</span>

          <div className="h-4 w-px bg-gray-800 hidden sm:block" />

          <div className="flex items-center gap-1.5 sm:gap-2">
            {isConnected ? (
              <>
                <div className="status-healthy" />
                <Wifi size={16} className="text-goblin-500" />
              </>
            ) : (
              <>
                <div className="status-down" />
                <WifiOff size={16} className="text-red-500" />
              </>
            )}
            <span className="hidden sm:inline text-xs text-gray-400">
              {isConnected ? "Live" : "Disconnected"}
            </span>
          </div>
        </div>
      </header>
      {/* Price ticker bar below header */}
      <PriceTicker />
    </>
  );
}
