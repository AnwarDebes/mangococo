"use client";

import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import FloatingIsland from "../world/FloatingIsland";
import GoblinCharacter from "../characters/GoblinCharacter";
import type { FearGreedData, GlobalMarketData } from "@/types";
import type { TickerPrice } from "@/lib/api";
import type { Mesh, MeshStandardMaterial } from "three";

interface MarketSquareZoneProps {
  tickers: TickerPrice[];
  fearGreed?: FearGreedData;
  globalMarket?: GlobalMarketData;
}

/** Rotating market crystal */
function MarketCrystal({ fgValue }: { fgValue: number }) {
  const meshRef = useRef<Mesh>(null);
  const color = fgValue <= 25 ? "#ef4444" : fgValue <= 45 ? "#f59e0b" : fgValue <= 55 ? "#8b5cf6" : "#22c55e";

  useFrame(({ clock }) => {
    if (!meshRef.current) return;
    meshRef.current.rotation.y = clock.elapsedTime * 0.3;
    meshRef.current.rotation.x = Math.sin(clock.elapsedTime * 0.5) * 0.1;
    const pulse = 1 + Math.sin(clock.elapsedTime * 1.5) * 0.05;
    meshRef.current.scale.set(pulse, pulse, pulse);
  });

  return (
    <group position={[0, 3, 0]}>
      <mesh ref={meshRef}>
        <octahedronGeometry args={[0.8, 2]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.6} transparent opacity={0.5} wireframe />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.4, 12, 12]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.8} transparent opacity={0.3} />
      </mesh>
    </group>
  );
}

/** Ticker signboard */
function TickerBoard({ tickers }: { tickers: TickerPrice[] }) {
  const sorted = useMemo(() => {
    return [...tickers].sort((a, b) =>
      Math.abs(Number(b.priceChangePercent)) - Math.abs(Number(a.priceChangePercent))
    );
  }, [tickers]);

  return (
    <Html position={[3, 2, 0]} distanceFactor={8} style={{ pointerEvents: "none" }}>
      <div className="bg-gray-950/90 backdrop-blur border border-blue-600/30 rounded-lg px-3 py-2 min-w-[160px]">
        <div className="text-blue-400 text-[9px] font-bold uppercase tracking-wider mb-1">Live Prices</div>
        <div className="space-y-0.5">
          {sorted.slice(0, 8).map((t) => {
            const pct = Number(t.priceChangePercent);
            const up = pct >= 0;
            return (
              <div key={t.symbol} className="flex items-center justify-between text-[10px] gap-2">
                <span className="text-white font-medium">{t.symbol.replace("USDT", "")}</span>
                <span className="text-gray-400">${Number(t.lastPrice).toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
                <span className={`font-bold ${up ? "text-green-400" : "text-red-400"}`}>
                  {up ? "+" : ""}{pct.toFixed(1)}%
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </Html>
  );
}

/** Pulse ring when prices move significantly */
function PricePulse({ tickers }: { tickers: TickerPrice[] }) {
  const meshRef = useRef<Mesh>(null);
  const scaleRef = useRef(1);

  const maxChange = useMemo(() => {
    if (!tickers.length) return 0;
    return Math.max(...tickers.map((t) => Math.abs(Number(t.priceChangePercent))));
  }, [tickers]);

  const active = maxChange > 2;

  useFrame((_, delta) => {
    if (!meshRef.current || !active) return;
    scaleRef.current += delta * 4;
    if (scaleRef.current > 10) scaleRef.current = 1;
    const opacity = Math.max(0, 0.2 * (1 - scaleRef.current / 10));
    meshRef.current.scale.set(scaleRef.current, scaleRef.current, 1);
    const mat = meshRef.current.material as MeshStandardMaterial;
    mat.opacity = opacity;
  });

  if (!active) return null;

  return (
    <mesh ref={meshRef} rotation={[Math.PI / 2, 0, 0]} position={[0, 0.1, 0]}>
      <torusGeometry args={[1, 0.02, 8, 24]} />
      <meshStandardMaterial color="#3b82f6" emissive="#3b82f6" emissiveIntensity={0.5} transparent opacity={0.2} />
    </mesh>
  );
}

export default function MarketSquareZone({ tickers, fearGreed, globalMarket }: MarketSquareZoneProps) {
  const fgValue = Number(fearGreed?.data?.[0]?.value ?? 50);
  const fgLabel = fearGreed?.data?.[0]?.value_classification ?? "Neutral";
  const marketCap = globalMarket?.data?.total_market_cap?.usd;
  const btcDom = globalMarket?.data?.market_cap_percentage?.btc;

  return (
    <FloatingIsland
      position={[19, 0, -6]}
      radius={5}
      height={0.6}
      color="#0c2240"
      glowColor="#3b82f6"
    >
      <MarketCrystal fgValue={fgValue} />
      <TickerBoard tickers={tickers} />
      <PricePulse tickers={tickers} />

      {/* Market info overlay */}
      <Html position={[-3, 2.5, 0]} distanceFactor={8} style={{ pointerEvents: "none" }}>
        <div className="bg-gray-950/90 backdrop-blur border border-blue-600/30 rounded-lg px-3 py-2 text-center min-w-[130px]">
          <div className="text-blue-400 text-[9px] font-bold uppercase tracking-wider">World Mood</div>
          <div className={`text-lg font-black ${fgValue <= 25 ? "text-red-400" : fgValue <= 45 ? "text-orange-400" : fgValue <= 55 ? "text-gray-300" : "text-green-400"}`}>
            {fgLabel}
          </div>
          <div className="text-[10px] text-gray-400">{fgValue}/100</div>
          {marketCap && (
            <div className="text-[10px] text-gray-400 mt-1">
              Cap: ${(marketCap / 1e12).toFixed(2)}T
            </div>
          )}
          {btcDom != null && (
            <div className="text-[10px] text-orange-300">
              BTC: {btcDom.toFixed(1)}%
            </div>
          )}
        </div>
      </Html>

      {/* Scout goblin */}
      <GoblinCharacter
        name="Market Scout"
        title="The Analyst"
        role="scout"
        outfitColor="#1e3a5f"
        status="online"
        hp={fgValue}
        level={tickers.length}
        speechText={`Tracking ${tickers.length} markets! Mood: ${fgLabel}`}
        position={[-2, 0, 2]}
        scale={0.8}
      />
    </FloatingIsland>
  );
}
