"use client";

import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import FloatingIsland from "../world/FloatingIsland";
import GoblinCharacter from "../characters/GoblinCharacter";
import type { Position, SystemHealth } from "@/types";
import type { Mesh, MeshStandardMaterial } from "three";

interface GuardTowerZoneProps {
  positions: Position[];
  health: SystemHealth[];
}

/** Watchtower structure */
function Watchtower({ riskLevel }: { riskLevel: number }) {
  return (
    <group position={[0, 0, -1]}>
      {/* Tower base */}
      <mesh position={[0, 1, 0]}>
        <cylinderGeometry args={[0.4, 0.6, 2, 6]} />
        <meshStandardMaterial color="#374151" metalness={0.4} roughness={0.6} />
      </mesh>
      {/* Tower top / lookout */}
      <mesh position={[0, 2.3, 0]}>
        <cylinderGeometry args={[0.7, 0.4, 0.5, 6]} />
        <meshStandardMaterial color="#4b5563" metalness={0.3} roughness={0.7} />
      </mesh>
      {/* Beacon fire */}
      <mesh position={[0, 2.8, 0]}>
        <sphereGeometry args={[0.2, 8, 8]} />
        <meshStandardMaterial
          color={riskLevel > 70 ? "#ef4444" : riskLevel > 40 ? "#f59e0b" : "#22c55e"}
          emissive={riskLevel > 70 ? "#ef4444" : riskLevel > 40 ? "#f59e0b" : "#22c55e"}
          emissiveIntensity={1}
          transparent
          opacity={0.8}
        />
      </mesh>
    </group>
  );
}

/** Risk shield visualization */
function RiskShield({ riskLevel }: { riskLevel: number }) {
  const meshRef = useRef<Mesh>(null);

  useFrame(({ clock }) => {
    if (!meshRef.current) return;
    const mat = meshRef.current.material as MeshStandardMaterial;
    mat.emissiveIntensity = 0.2 + Math.sin(clock.elapsedTime * 2) * 0.1;
    meshRef.current.rotation.y = clock.elapsedTime * 0.3;
  });

  const color = riskLevel > 70 ? "#ef4444" : riskLevel > 40 ? "#f59e0b" : "#22c55e";

  return (
    <group position={[2, 1.5, 0]}>
      {/* Shield */}
      <mesh ref={meshRef}>
        <circleGeometry args={[0.6, 6]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={0.3}
          transparent
          opacity={0.5}
          side={2}
        />
      </mesh>
      <Html position={[0, 1, 0]} distanceFactor={8} center style={{ pointerEvents: "none" }}>
        <div className="bg-gray-950/90 backdrop-blur border border-red-600/30 rounded-lg px-3 py-1.5 text-center">
          <div className="text-red-400 text-[9px] font-bold uppercase">Risk Level</div>
          <div className={`text-xl font-black ${riskLevel > 70 ? "text-red-400" : riskLevel > 40 ? "text-yellow-400" : "text-green-400"}`}>
            {riskLevel}%
          </div>
        </div>
      </Html>
    </group>
  );
}

/** Pulsing alert aura when risk is high */
function RiskAura({ riskLevel }: { riskLevel: number }) {
  const meshRef = useRef<Mesh>(null);

  useFrame(({ clock }) => {
    if (!meshRef.current) return;
    const mat = meshRef.current.material as MeshStandardMaterial;
    const baseOpacity = riskLevel > 70 ? 0.15 : riskLevel > 40 ? 0.05 : 0;
    mat.opacity = baseOpacity + Math.sin(clock.elapsedTime * 3) * 0.05;
  });

  if (riskLevel <= 30) return null;

  return (
    <mesh ref={meshRef} position={[0, 1, 0]}>
      <sphereGeometry args={[4, 16, 16]} />
      <meshStandardMaterial
        color="#ef4444"
        emissive="#ef4444"
        emissiveIntensity={0.2}
        transparent
        opacity={0.1}
        side={1}
      />
    </mesh>
  );
}

export default function GuardTowerZone({ positions, health }: GuardTowerZoneProps) {
  const riskLevel = useMemo(() => {
    if (!positions.length) return 0;
    const losingCount = positions.filter((p) => p.unrealized_pnl < 0).length;
    const losingRatio = losingCount / positions.length;
    const totalLoss = positions
      .filter((p) => p.unrealized_pnl < 0)
      .reduce((s, p) => s + Math.abs(p.unrealized_pnl), 0);
    const lossScore = Math.min(50, totalLoss / 10);
    const ratioScore = losingRatio * 50;
    return Math.round(Math.min(100, lossScore + ratioScore));
  }, [positions]);

  const healthyServices = health.filter((s) => s.status === "healthy").length;
  const totalServices = health.length;
  const losingPositions = positions.filter((p) => p.unrealized_pnl < 0);

  return (
    <FloatingIsland
      position={[-19, 0, -6]}
      radius={5}
      height={0.6}
      color="#450a0a"
      glowColor="#ef4444"
    >
      <Watchtower riskLevel={riskLevel} />
      <RiskShield riskLevel={riskLevel} />
      <RiskAura riskLevel={riskLevel} />

      {/* Guardian goblin */}
      <GoblinCharacter
        name="Sentinel"
        title="The Guardian"
        role="guardian"
        outfitColor="#7f1d1d"
        status={riskLevel > 70 ? "degraded" : "online"}
        hp={100 - riskLevel}
        level={totalServices}
        speechText={
          riskLevel > 70
            ? "Danger! Multiple threats detected!"
            : riskLevel > 40
              ? "Stay alert, risks detected..."
              : "All quiet on the front."
        }
        metrics={[
          { label: "Risk", value: `${riskLevel}%`, color: riskLevel > 70 ? "#ef4444" : riskLevel > 40 ? "#f59e0b" : "#22c55e" },
          { label: "Services", value: `${healthyServices}/${totalServices}`, color: healthyServices === totalServices ? "#22c55e" : "#f59e0b" },
          { label: "Losing", value: `${losingPositions.length}`, color: losingPositions.length > 0 ? "#ef4444" : "#22c55e" },
        ]}
        position={[-2, 0, 1]}
        scale={0.9}
      />
    </FloatingIsland>
  );
}
