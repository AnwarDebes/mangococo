"use client";

import { useEffect, useState } from "react";
import { Wifi, WifiOff } from "lucide-react";
import { useSSE } from "@/hooks/useSSE";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export default function Header() {
  const { isConnected } = useSSE(`${API_BASE}/api/stream`);
  const [currentTime, setCurrentTime] = useState("");

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

  return (
    <header className="flex h-16 items-center justify-between border-b border-gray-800 bg-gray-950 px-6">
      <div className="lg:hidden w-10" />
      <div className="flex items-center gap-4 ml-auto">
        <span className="text-sm font-mono text-gray-400">{currentTime}</span>
        <div className="flex items-center gap-2">
          {isConnected ? (
            <>
              <div className="status-healthy" />
              <Wifi size={16} className="text-green-500" />
            </>
          ) : (
            <>
              <div className="status-down" />
              <WifiOff size={16} className="text-red-500" />
            </>
          )}
          <span className="text-xs text-gray-400">
            {isConnected ? "Live" : "Disconnected"}
          </span>
        </div>
      </div>
    </header>
  );
}
