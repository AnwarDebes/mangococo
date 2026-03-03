"use client";

import { useEffect, useRef, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { getModelStatus, getSignals } from "@/lib/api";

const RING_CONFIG = [
  { label: "Technical", dots: ["RSI", "MACD", "Boll", "Vol", "EMA20", "EMA50", "ATR", "OBV"], radius: 55, speed: 10, dir: 1 },
  { label: "TCN", dots: ["T1", "T2", "T3", "T4", "T5", "T6"], radius: 75, speed: 15, dir: -1 },
  { label: "XGBoost", dots: ["X1", "X2", "X3", "X4", "X5", "X6"], radius: 95, speed: 12, dir: 1 },
  { label: "External", dots: ["News", "Social", "F&G", "Whale"], radius: 120, speed: 20, dir: -1 },
];

export default function NeuralPulse() {
  const canvasRef = useRef<SVGSVGElement>(null);
  const rotationRef = useRef(0);
  const animRef = useRef<number>(0);
  const pulseRef = useRef(0);
  const prefersReducedMotion = useRef(false);

  const { data: models } = useQuery({
    queryKey: ["models"],
    queryFn: getModelStatus,
    refetchInterval: 5000,
  });

  const { data: signals } = useQuery({
    queryKey: ["signals-pulse"],
    queryFn: getSignals,
    refetchInterval: 5000,
  });

  const latestSignal = signals?.[0];
  const isBullish = latestSignal?.action === "BUY";
  const isBearish = latestSignal?.action === "SELL";
  const orbColor = isBullish ? "#22c55e" : isBearish ? "#ef4444" : "#f59e0b";

  const tcnActive = models?.some((m) => m.model_name === "tcn" && m.status === "active");
  const xgbActive = models?.some((m) => m.model_name === "xgboost" && m.status === "active");
  const tcnConf = models?.find((m) => m.model_name === "tcn")?.accuracy ?? 0.5;
  const xgbConf = models?.find((m) => m.model_name === "xgboost")?.accuracy ?? 0.5;

  useEffect(() => {
    prefersReducedMotion.current = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }, []);

  // Trigger pulse on new signal
  useEffect(() => {
    if (latestSignal) {
      pulseRef.current = Date.now();
    }
  }, [latestSignal?.signal_id]);

  // Animation loop
  useEffect(() => {
    let lastTime = 0;
    const animate = (time: number) => {
      if (!prefersReducedMotion.current) {
        const delta = lastTime ? (time - lastTime) / 1000 : 0;
        lastTime = time;
        rotationRef.current += delta;
      }
      animRef.current = requestAnimationFrame(animate);
    };
    animRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animRef.current);
  }, []);

  const cx = 150;
  const cy = 160;

  return (
    <div className="flex h-full flex-col items-center">
      <p className="text-xs text-gray-500 mb-2">Neural Activity</p>
      <svg
        ref={canvasRef}
        viewBox="0 0 300 320"
        className="w-full max-w-[300px]"
      >
        {/* Connection lines */}
        {RING_CONFIG.map((ring, ri) =>
          ring.dots.map((_, di) => {
            const angle = (di / ring.dots.length) * Math.PI * 2;
            const x = cx + Math.cos(angle) * ring.radius;
            const y = cy + Math.sin(angle) * ring.radius;
            return (
              <line
                key={`line-${ri}-${di}`}
                x1={cx} y1={cy} x2={x} y2={y}
                stroke="#374151" strokeWidth={0.5} opacity={0.15}
              />
            );
          })
        )}

        {/* Ring orbits */}
        {RING_CONFIG.map((ring, ri) => (
          <circle
            key={`orbit-${ri}`}
            cx={cx} cy={cy} r={ring.radius}
            fill="none" stroke="#1f2937" strokeWidth={0.5}
          />
        ))}

        {/* Orbital dots */}
        {RING_CONFIG.map((ring, ri) =>
          ring.dots.map((label, di) => {
            const baseAngle = (di / ring.dots.length) * Math.PI * 2;
            const rotSpeed = (Math.PI * 2) / ring.speed;
            const angle = baseAngle + rotationRef.current * rotSpeed * ring.dir;
            const x = cx + Math.cos(angle) * ring.radius;
            const y = cy + Math.sin(angle) * ring.radius;

            let dotColor = "#6b7280";
            let dotSize = 4;
            if (ri === 0) {
              // Technical: alternate colors based on signal
              dotColor = isBullish ? "#22c55e" : isBearish ? "#ef4444" : "#6b7280";
              dotSize = 3.5;
            } else if (ri === 1) {
              dotColor = tcnActive ? "#22c55e" : "#6b7280";
              dotSize = 3 + tcnConf * 3;
            } else if (ri === 2) {
              dotColor = xgbActive ? "#22c55e" : "#6b7280";
              dotSize = 3 + xgbConf * 3;
            } else {
              dotSize = 5;
              dotColor = isBullish ? "#22c55e" : isBearish ? "#ef4444" : "#f59e0b";
            }

            return (
              <g key={`dot-${ri}-${di}`}>
                <circle cx={x} cy={y} r={dotSize} fill={dotColor} opacity={0.8}>
                  <animateTransform
                    attributeName="transform"
                    type="rotate"
                    from={`0 ${cx} ${cy}`}
                    to={`${360 * ring.dir} ${cx} ${cy}`}
                    dur={`${ring.speed}s`}
                    repeatCount="indefinite"
                  />
                </circle>
              </g>
            );
          })
        )}

        {/* Center orb */}
        <circle cx={cx} cy={cy} r={28} fill={orbColor} opacity={0.15} />
        <circle cx={cx} cy={cy} r={22} fill={orbColor} opacity={0.25}>
          <animate
            attributeName="r"
            values="22;23;22"
            dur="3s"
            repeatCount="indefinite"
          />
        </circle>
        <circle cx={cx} cy={cy} r={16} fill={orbColor} opacity={0.4} />

        {/* Pulse ring */}
        <circle cx={cx} cy={cy} r={30} fill="none" stroke={orbColor} strokeWidth={2} opacity={0}>
          <animate
            attributeName="r"
            values="30;130"
            dur="2s"
            repeatCount="indefinite"
          />
          <animate
            attributeName="opacity"
            values="0.4;0"
            dur="2s"
            repeatCount="indefinite"
          />
        </circle>

        {/* Center label */}
        <text x={cx} y={cy + 4} textAnchor="middle" fill="white" fontSize={10} fontWeight={600}>
          AI
        </text>

        {/* Ring labels */}
        {RING_CONFIG.map((ring, ri) => (
          <text
            key={`rlabel-${ri}`}
            x={cx}
            y={cy - ring.radius - 6}
            textAnchor="middle"
            fill="#4b5563"
            fontSize={8}
          >
            {ring.label}
          </text>
        ))}

        {/* Status text */}
        <text x={cx} y={310} textAnchor="middle" fill="#9ca3af" fontSize={10}>
          {isBullish ? "Bullish Signal Active" : isBearish ? "Bearish Signal Active" : "Monitoring Markets"}
        </text>
      </svg>
    </div>
  );
}
