"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import type { Group } from "three";
import type { Position } from "@/types";

interface PositionWarriorProps {
  position: Position;
  index: number;
  total: number;
}

const SKIN = "#6dd676";

export default function PositionWarrior({ position: pos, index, total }: PositionWarriorProps) {
  const groupRef = useRef<Group>(null);
  const bobRef = useRef(index * 1.3);

  const isProfitable = pos.unrealized_pnl >= 0;
  const armorColor = isProfitable ? "#166534" : "#7f1d1d";
  const glowColor = isProfitable ? "#22c55e" : "#ef4444";
  const pnlPct = pos.entry_price > 0
    ? ((pos.current_price - pos.entry_price) / pos.entry_price) * 100
    : 0;

  // Position in a circle
  const angle = (index / Math.max(total, 1)) * Math.PI * 2;
  const radius = 1.5;
  const x = Math.cos(angle) * radius;
  const z = Math.sin(angle) * radius;

  useFrame((_, delta) => {
    if (!groupRef.current) return;
    bobRef.current += delta * 1.2;
    groupRef.current.position.y = Math.sin(bobRef.current) * 0.03;
    // Face outward
    groupRef.current.rotation.y = angle;
  });

  return (
    <group ref={groupRef} position={[x, 0, z]} scale={0.6}>
      {/* Legs */}
      <mesh position={[-0.08, 0.15, 0]}>
        <capsuleGeometry args={[0.04, 0.15, 4, 6]} />
        <meshStandardMaterial color={SKIN} />
      </mesh>
      <mesh position={[0.08, 0.15, 0]}>
        <capsuleGeometry args={[0.04, 0.15, 4, 6]} />
        <meshStandardMaterial color={SKIN} />
      </mesh>

      {/* Body */}
      <mesh position={[0, 0.5, 0]}>
        <capsuleGeometry args={[0.16, 0.2, 4, 8]} />
        <meshStandardMaterial color={armorColor} />
      </mesh>

      {/* Head */}
      <mesh position={[0, 0.85, 0]}>
        <sphereGeometry args={[0.2, 8, 8]} />
        <meshStandardMaterial color={SKIN} />
      </mesh>

      {/* Ears */}
      <mesh position={[-0.22, 0.9, 0]} rotation={[0, 0, -0.8]}>
        <coneGeometry args={[0.04, 0.16, 4]} />
        <meshStandardMaterial color={SKIN} />
      </mesh>
      <mesh position={[0.22, 0.9, 0]} rotation={[0, 0, 0.8]}>
        <coneGeometry args={[0.04, 0.16, 4]} />
        <meshStandardMaterial color={SKIN} />
      </mesh>

      {/* Tiny sword */}
      <mesh position={[0.3, 0.5, 0]} rotation={[0, 0, -0.3]}>
        <boxGeometry args={[0.03, 0.4, 0.015]} />
        <meshStandardMaterial color="#d1d5db" metalness={0.9} roughness={0.1} />
      </mesh>

      {/* P&L aura */}
      <mesh position={[0, 0.5, 0]}>
        <sphereGeometry args={[0.35, 8, 8]} />
        <meshStandardMaterial
          color={glowColor}
          emissive={glowColor}
          emissiveIntensity={0.3}
          transparent
          opacity={0.1}
        />
      </mesh>

      {/* Label */}
      <Html position={[0, 1.5, 0]} distanceFactor={7} center style={{ pointerEvents: "none" }}>
        <div className="bg-black/85 backdrop-blur rounded px-2 py-0.5 border border-white/10 text-center whitespace-nowrap">
          <div className="text-[10px] font-bold text-white">{pos.symbol}</div>
          <div className="flex items-center gap-1 justify-center">
            <span className={`text-[9px] font-bold ${pos.side === "long" ? "text-green-400" : "text-red-400"}`}>
              {pos.side.toUpperCase()}
            </span>
            <span className={`text-[9px] font-bold ${isProfitable ? "text-green-400" : "text-red-400"}`}>
              {isProfitable ? "+" : ""}{pnlPct.toFixed(1)}%
            </span>
          </div>
          <div className="text-[8px] text-gray-400">
            ${Math.abs(pos.unrealized_pnl).toFixed(2)}
          </div>
        </div>
      </Html>
    </group>
  );
}
