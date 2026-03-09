"use client";

import { Canvas } from "@react-three/fiber";
import { AdaptiveDpr, Html, Stars, Line } from "@react-three/drei";
import { EffectComposer, Bloom, Vignette } from "@react-three/postprocessing";
import { Suspense, useMemo } from "react";
import * as THREE from "three";

import { ZONES } from "./zones/ZoneConfig";
import { useNerveCenterStore } from "./NerveCenterStore";
import { useNerveCenterData } from "@/hooks/useNerveCenterData";

// Zone content
import TreasuryZone from "./zones/TreasuryZone";
import WarRoomZone from "./zones/WarRoomZone";
import OracleTowerZone from "./zones/OracleTowerZone";
import WizardAcademyZone from "./zones/WizardAcademyZone";
import GuardTowerZone from "./zones/GuardTowerZone";
import MarketSquareZone from "./zones/MarketSquareZone";

// Effects
import LiveDataNetwork from "./effects/LiveDataNetwork";
import CommunicationManager from "./effects/CommunicationManager";
import AmbientMagic from "./effects/AmbientMagic";

// Player
import PlayerController from "./PlayerController";

// Service goblins (between zones)
import GoblinCharacter from "./characters/GoblinCharacter";
import type { GoblinRole, GoblinMetric } from "./characters/GoblinCharacter";
import FloatingIsland from "./world/FloatingIsland";

/* ── Service → Goblin mapping ───────────────────────────────────── */

interface ServiceGoblinConfig {
  role: GoblinRole;
  title: string;
  outfitColor: string;
  glowColor: string;
}

const SERVICE_MAP: Record<string, ServiceGoblinConfig> = {
  trading_engine: { role: "merchant", title: "The Merchant", outfitColor: "#166534", glowColor: "#22c55e" },
  signal_generator: { role: "oracle", title: "The Oracle", outfitColor: "#155e75", glowColor: "#06b6d4" },
  risk_manager: { role: "guardian", title: "The Guardian", outfitColor: "#7f1d1d", glowColor: "#ef4444" },
  data_pipeline: { role: "scout", title: "The Scout", outfitColor: "#1e3a5f", glowColor: "#3b82f6" },
  sentiment_analyzer: { role: "oracle", title: "The Seer", outfitColor: "#4c1d95", glowColor: "#8b5cf6" },
  portfolio_manager: { role: "treasurer", title: "The Treasurer", outfitColor: "#78350f", glowColor: "#f59e0b" },
  api_gateway: { role: "scout", title: "The Messenger", outfitColor: "#1e3a5f", glowColor: "#60a5fa" },
  scheduler: { role: "merchant", title: "The Timekeeper", outfitColor: "#3f3f46", glowColor: "#a1a1aa" },
};

function getServiceConfig(name: string): ServiceGoblinConfig {
  const key = name.toLowerCase().replace(/[\s-]/g, "_");
  return SERVICE_MAP[key] ?? { role: "scout" as GoblinRole, title: "Minion", outfitColor: "#374151", glowColor: "#6b7280" };
}

/* ── Service outposts between zones ─────────────────────────────── */

function ServiceOutposts() {
  const data = useNerveCenterData();

  const outposts = useMemo(() => {
    if (!data.health.length) return [];
    const count = data.health.length;
    const outerRadius = 28;
    return data.health.map((svc, i) => {
      const angle = (i / count) * Math.PI * 2 + Math.PI / 6;
      const x = Math.cos(angle) * outerRadius;
      const z = Math.sin(angle) * outerRadius;
      const cfg = getServiceConfig(svc.service_name);
      const hpVal = svc.status === "healthy" ? 100 : svc.status === "degraded" ? 50 : 0;
      const level = Math.max(1, Math.min(99, Math.floor(svc.uptime / 3600)));
      const upStr = svc.uptime > 3600 ? `${(svc.uptime / 3600).toFixed(1)}h` : `${Math.round(svc.uptime / 60)}m`;
      const speech = svc.status === "down" ? `Fallen! Was up ${upStr}` : `On duty for ${upStr}`;
      const metrics: GoblinMetric[] = [
        { label: "Status", value: svc.status.toUpperCase(), color: hpVal === 100 ? "#22c55e" : hpVal > 0 ? "#f59e0b" : "#ef4444" },
      ];
      return { svc, x, z, cfg, hpVal, level, metrics, speech };
    });
  }, [data.health]);

  return (
    <>
      {outposts.map(({ svc, x, z, cfg, hpVal, level, metrics, speech }) => (
        <FloatingIsland key={svc.service_name} position={[x, -2, z]} radius={1.8} height={0.4} color="#1f2937" glowColor={cfg.glowColor}>
          <GoblinCharacter
            name={svc.service_name.replace(/_/g, " ")}
            title={cfg.title}
            role={cfg.role}
            outfitColor={cfg.outfitColor}
            status={svc.status === "healthy" ? "online" : svc.status === "degraded" ? "degraded" : "offline"}
            hp={hpVal}
            level={level}
            speechText={speech}
            metrics={metrics}
            scale={0.7}
          />
        </FloatingIsland>
      ))}
    </>
  );
}

/* ── Zone labels visible from distance ──────────────────────────── */

function ZoneLabels() {
  return (
    <group>
      {ZONES.map((zone) => (
        <Html
          key={zone.id}
          position={[zone.position[0], zone.position[1] + 7, zone.position[2]]}
          distanceFactor={25}
          center
          style={{ pointerEvents: "none" }}
        >
          <div className="text-center select-none">
            <div className="text-2xl">{zone.icon}</div>
            <div className="text-sm font-bold tracking-wide uppercase" style={{ color: zone.glowColor, textShadow: `0 0 10px ${zone.glowColor}40` }}>
              {zone.name}
            </div>
          </div>
        </Html>
      ))}
    </group>
  );
}

/* ── Zone hex boundary markers ──────────────────────────────────── */

function ZoneBoundaries() {
  return (
    <group>
      {ZONES.map((zone) => {
        const hexPoints: [number, number, number][] = [];
        for (let i = 0; i <= 6; i++) {
          const a = (i / 6) * Math.PI * 2;
          hexPoints.push([
            zone.position[0] + Math.cos(a) * (zone.islandRadius + 2),
            -2.8,
            zone.position[2] + Math.sin(a) * (zone.islandRadius + 2),
          ]);
        }
        return <Line key={zone.id} points={hexPoints} color={zone.glowColor} transparent opacity={0.12} lineWidth={1} />;
      })}
    </group>
  );
}

/* ── Ground with kingdom roads ──────────────────────────────────── */

function KingdomGround() {
  return (
    <group>
      {/* Main ground */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -3, 0]}>
        <circleGeometry args={[55, 64]} />
        <meshStandardMaterial color="#060d18" />
      </mesh>
      <gridHelper args={[100, 50, "#1e293b", "#0f172a"]} position={[0, -2.9, 0]} />

      {/* Glowing roads between zones (on ground) */}
      {ZONES.filter((z) => z.id !== "treasury").map((zone) => {
        const start: [number, number, number] = [0, -2.85, 0];
        const end: [number, number, number] = [zone.position[0], -2.85, zone.position[2]];
        return (
          <Line
            key={`road-${zone.id}`}
            points={[start, end]}
            color={zone.glowColor}
            transparent
            opacity={0.06}
            lineWidth={3}
          />
        );
      })}
    </group>
  );
}

/* ── Main scene content ─────────────────────────────────────────── */

function SceneContent() {
  const data = useNerveCenterData();
  const particleCount = useNerveCenterStore((s) => s.particleCount);
  const magicCount = particleCount === "low" ? 200 : particleCount === "medium" ? 400 : 700;

  if (data.isLoading) {
    return (
      <Html center>
        <div className="text-center">
          <div className="text-amber-400 text-2xl font-bold animate-pulse mb-2">Summoning the Kingdom...</div>
          <div className="text-gray-500 text-sm">Loading realm data</div>
        </div>
      </Html>
    );
  }

  return (
    <>
      {/* Environment */}
      <Stars radius={100} depth={60} count={2500} factor={4} saturation={0.5} fade speed={0.8} />
      <ambientLight intensity={0.35} />
      <directionalLight position={[15, 25, 15]} intensity={0.7} color="#fff4e6" />
      <directionalLight position={[-15, 20, -15]} intensity={0.25} color="#bfdbfe" />
      <fog attach="fog" args={["#030712", 40, 100]} />

      {/* Ground */}
      <KingdomGround />

      {/* Zone lights */}
      {ZONES.map((zone) => (
        <pointLight key={zone.id} position={[zone.position[0], zone.position[1] + 4, zone.position[2]]} color={zone.lightColor} intensity={0.6} distance={20} decay={2} />
      ))}
      <pointLight position={[0, 8, 0]} color="#fbbf24" intensity={0.8} distance={25} decay={2} />

      {/* Zone Content */}
      <TreasuryZone portfolio={data.portfolio} positions={data.positions} />
      <WarRoomZone positions={data.positions} />
      <OracleTowerZone signals={data.signals} />
      <WizardAcademyZone models={data.models} />
      <GuardTowerZone positions={data.positions} health={data.health} />
      <MarketSquareZone tickers={data.tickers} fearGreed={data.fearGreed} globalMarket={data.globalMarket} />

      {/* Labels & Boundaries */}
      <ZoneLabels />
      <ZoneBoundaries />

      {/* Service Outposts */}
      <ServiceOutposts />

      {/* Live Communication Effects */}
      <LiveDataNetwork />
      <CommunicationManager />
      <AmbientMagic count={magicCount} />

      {/* Player Controller (GTA-style) */}
      <PlayerController />

      {/* Post-processing */}
      <EffectComposer>
        <Bloom intensity={0.35} luminanceThreshold={0.65} luminanceSmoothing={0.4} />
        <Vignette darkness={0.4} offset={0.3} />
      </EffectComposer>
    </>
  );
}

/* ── Main Export ─────────────────────────────────────────────────── */

export default function NerveCenterScene() {
  return (
    <Canvas
      gl={{ antialias: true, alpha: false }}
      dpr={[1, 2]}
      camera={{ position: [0, 10, 35], fov: 55, near: 0.5, far: 200 }}
      style={{ background: "#030712" }}
    >
      <AdaptiveDpr pixelated />
      <Suspense fallback={null}>
        <SceneContent />
      </Suspense>
    </Canvas>
  );
}
