"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import FloatingIsland from "../world/FloatingIsland";
import PositionWarrior from "../characters/PositionWarrior";
import GoblinCharacter from "../characters/GoblinCharacter";
import type { Position } from "@/types";
import type { Mesh, MeshStandardMaterial } from "three";

interface WarRoomZoneProps {
  positions: Position[];
}

/** War table showing position summary */
function WarTable({ positions }: { positions: Position[] }) {
  const totalPnl = positions.reduce((s, p) => s + p.unrealized_pnl, 0);
  const winning = positions.filter((p) => p.unrealized_pnl >= 0).length;
  const isProfitable = totalPnl >= 0;

  return (
    <group position={[0, 0.4, 0]}>
      {/* Table surface */}
      <mesh position={[0, 0.3, 0]}>
        <cylinderGeometry args={[1.5, 1.5, 0.08, 12]} />
        <meshStandardMaterial color="#1e293b" metalness={0.3} roughness={0.7} />
      </mesh>
      {/* Table legs */}
      {[0, Math.PI / 2, Math.PI, (3 * Math.PI) / 2].map((a, i) => (
        <mesh key={i} position={[Math.cos(a) * 1.2, 0.15, Math.sin(a) * 1.2]}>
          <cylinderGeometry args={[0.05, 0.05, 0.3, 6]} />
          <meshStandardMaterial color="#374151" />
        </mesh>
      ))}
      {/* Status glow */}
      <mesh position={[0, 0.36, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[1.4, 12]} />
        <meshStandardMaterial
          color={isProfitable ? "#22c55e" : "#ef4444"}
          emissive={isProfitable ? "#22c55e" : "#ef4444"}
          emissiveIntensity={0.1}
          transparent
          opacity={0.3}
        />
      </mesh>
      <Html position={[0, 0.8, 0]} distanceFactor={8} center style={{ pointerEvents: "none" }}>
        <div className="bg-gray-950/90 backdrop-blur border border-green-600/30 rounded-lg px-3 py-2 text-center min-w-[140px]">
          <div className="text-green-400 text-[9px] font-bold uppercase tracking-wider">Battle Status</div>
          <div className={`text-lg font-black ${isProfitable ? "text-green-400" : "text-red-400"}`}>
            {isProfitable ? "+" : ""}${totalPnl.toFixed(2)}
          </div>
          <div className="text-[10px] text-gray-400">
            {winning}/{positions.length} winning
          </div>
        </div>
      </Html>
    </group>
  );
}

/** Pulsing impact ring when new trades happen */
function BattleRing() {
  const meshRef = useRef<Mesh>(null);
  const scaleRef = useRef(1);

  useFrame((_, delta) => {
    if (!meshRef.current) return;
    scaleRef.current += delta * 3;
    if (scaleRef.current > 12) scaleRef.current = 1;
    const opacity = Math.max(0, 0.3 * (1 - scaleRef.current / 12));
    meshRef.current.scale.set(scaleRef.current, scaleRef.current, 1);
    const mat = meshRef.current.material as MeshStandardMaterial;
    mat.opacity = opacity;
  });

  return (
    <mesh ref={meshRef} rotation={[Math.PI / 2, 0, 0]} position={[0, 0.1, 0]}>
      <torusGeometry args={[1, 0.03, 8, 32]} />
      <meshStandardMaterial color="#22c55e" emissive="#22c55e" emissiveIntensity={0.5} transparent opacity={0.3} />
    </mesh>
  );
}

export default function WarRoomZone({ positions }: WarRoomZoneProps) {
  return (
    <FloatingIsland
      position={[0, 0, -20]}
      radius={6}
      height={0.6}
      color="#14532d"
      glowColor="#22c55e"
    >
      <WarTable positions={positions} />
      <BattleRing />

      {/* Position warriors in formation around the war table */}
      <group position={[0, 0, 0]}>
        {positions.map((pos, i) => (
          <PositionWarrior
            key={pos.symbol + i}
            position={pos}
            index={i}
            total={positions.length}
          />
        ))}
      </group>

      {/* War Room commander goblin */}
      <GoblinCharacter
        name="War Commander"
        title="Battle Strategist"
        role="warrior"
        outfitColor="#166534"
        status="online"
        hp={100}
        level={positions.length}
        speechText={`Commanding ${positions.length} warriors in battle!`}
        position={[0, 0, 3]}
        scale={0.8}
      />
    </FloatingIsland>
  );
}
