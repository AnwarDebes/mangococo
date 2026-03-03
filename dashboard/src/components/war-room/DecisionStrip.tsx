"use client";

import { useRef, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { getSignals } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function DecisionStrip() {
  const scrollRef = useRef<HTMLDivElement>(null);

  const { data: signals = [] } = useQuery({
    queryKey: ["signals-strip"],
    queryFn: getSignals,
    refetchInterval: 10000,
  });

  const decisions = signals.slice(0, 30).reverse();

  // Auto-scroll to latest
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollLeft = scrollRef.current.scrollWidth;
    }
  }, [decisions.length]);

  return (
    <div className="flex flex-col h-full">
      <p className="text-xs text-gray-500 mb-1 font-medium">Decision Timeline</p>
      <div ref={scrollRef} className="flex-1 overflow-x-auto overflow-y-hidden min-h-0">
        <div className="flex items-center h-full min-w-max px-2 gap-0">
          {decisions.map((s, i) => {
            const color =
              s.action === "BUY"
                ? "#22c55e"
                : s.action === "SELL"
                ? "#ef4444"
                : "#6b7280";
            const size = 6 + s.confidence * 10;
            const nextS = decisions[i + 1];
            const lineColor = nextS
              ? nextS.action === "BUY"
                ? "#22c55e40"
                : nextS.action === "SELL"
                ? "#ef444440"
                : "#37415140"
              : "transparent";

            return (
              <div key={s.signal_id} className="flex items-center">
                <div className="flex flex-col items-center group relative">
                  <div
                    className="rounded-full transition-transform hover:scale-150 cursor-pointer"
                    style={{
                      width: size,
                      height: size,
                      backgroundColor: color,
                      boxShadow: `0 0 ${size}px ${color}40`,
                    }}
                  />
                  {/* Tooltip */}
                  <div className="absolute bottom-full mb-2 hidden group-hover:block z-10">
                    <div className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-[9px] text-white whitespace-nowrap">
                      <span className="font-bold">{s.symbol.replace("USDT", "")}</span>{" "}
                      <span style={{ color }}>{s.action}</span>{" "}
                      <span className="text-gray-400">{(s.confidence * 100).toFixed(0)}%</span>
                    </div>
                  </div>
                  <span className="text-[7px] text-gray-600 mt-0.5 hidden sm:block">
                    {new Date(s.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </span>
                </div>
                {i < decisions.length - 1 && (
                  <div
                    className="h-px w-6 sm:w-10"
                    style={{ backgroundColor: lineColor }}
                  />
                )}
              </div>
            );
          })}
          {decisions.length === 0 && (
            <div className="text-xs text-gray-600 px-4">No decisions yet</div>
          )}
        </div>
      </div>
    </div>
  );
}
