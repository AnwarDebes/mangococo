"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import type { Group, Mesh, MeshStandardMaterial } from "three";

interface TreasureVaultProps {
  totalValue: number;
  dailyPnl: number;
  cashBalance: number;
  positionsCount: number;
}

export default function TreasureVault({ totalValue, dailyPnl, cashBalance, positionsCount }: TreasureVaultProps) {
  const groupRef = useRef<Group>(null);
  const glowRef = useRef<Mesh>(null);
  const coinRefs = useRef<Group>(null);

  const isProfitable = dailyPnl >= 0;
  const chestColor = isProfitable ? "#f59e0b" : "#78350f";
  const glowColor = isProfitable ? "#fbbf24" : "#ef4444";

  useFrame(({ clock }) => {
    if (glowRef.current) {
      const mat = glowRef.current.material as MeshStandardMaterial;
      mat.emissiveIntensity = 0.5 + Math.sin(clock.elapsedTime * 2) * 0.3;
    }
    if (coinRefs.current) {
      coinRefs.current.rotation.y += 0.005;
    }
  });

  const fmt = (n: number) =>
    "$" + Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 });

  return (
    <group ref={groupRef}>
      {/* Chest base */}
      <mesh position={[0, 0.3, 0]}>
        <boxGeometry args={[1.2, 0.6, 0.8]} />
        <meshStandardMaterial color={chestColor} metalness={0.4} roughness={0.6} />
      </mesh>

      {/* Chest lid */}
      <mesh position={[0, 0.7, 0]}>
        <boxGeometry args={[1.25, 0.15, 0.85]} />
        <meshStandardMaterial color={chestColor} metalness={0.5} roughness={0.5} />
      </mesh>

      {/* Chest lock */}
      <mesh position={[0, 0.45, 0.42]}>
        <boxGeometry args={[0.15, 0.15, 0.05]} />
        <meshStandardMaterial color="#b45309" metalness={0.8} roughness={0.2} />
      </mesh>

      {/* Gold glow from inside */}
      <mesh ref={glowRef} position={[0, 0.85, 0]}>
        <sphereGeometry args={[0.4, 12, 12]} />
        <meshStandardMaterial
          color={glowColor}
          emissive={glowColor}
          emissiveIntensity={0.5}
          transparent
          opacity={0.2}
        />
      </mesh>

      {/* Floating coins */}
      <group ref={coinRefs}>
        {[0, 1.2, 2.4, 3.6, 4.8].map((angle, i) => (
          <mesh
            key={i}
            position={[Math.cos(angle) * 1.2, 1.2 + Math.sin(i * 1.5) * 0.3, Math.sin(angle) * 1.2]}
            rotation={[Math.PI / 2, 0, angle]}
          >
            <cylinderGeometry args={[0.12, 0.12, 0.03, 12]} />
            <meshStandardMaterial
              color="#fbbf24"
              metalness={0.9}
              roughness={0.1}
              emissive="#f59e0b"
              emissiveIntensity={0.4}
            />
          </mesh>
        ))}
      </group>

      {/* Info overlay */}
      <Html position={[0, 2.5, 0]} distanceFactor={8} center style={{ pointerEvents: "none" }}>
        <div className="flex flex-col items-center gap-1 select-none" style={{ minWidth: 180 }}>
          {/* Title */}
          <div className="bg-gradient-to-r from-amber-900/90 to-yellow-900/90 backdrop-blur border border-amber-500/40 rounded-lg px-4 py-2 text-center">
            <div className="text-amber-300 text-[10px] font-bold tracking-wider uppercase">
              Royal Treasury
            </div>
            <div className="text-xl font-black text-yellow-300 mt-0.5" style={{ textShadow: "0 0 10px rgba(251,191,36,0.5)" }}>
              {fmt(totalValue)}
            </div>
          </div>

          {/* Stats */}
          <div className="bg-black/80 backdrop-blur rounded-md px-3 py-1.5 border border-white/10">
            <div className="flex justify-between text-[10px] gap-3">
              <span className="text-gray-400">Daily Gold</span>
              <span className={isProfitable ? "text-green-400" : "text-red-400"}>
                {isProfitable ? "+" : "-"}{fmt(dailyPnl)}
              </span>
            </div>
            <div className="flex justify-between text-[10px] gap-3">
              <span className="text-gray-400">Reserves</span>
              <span className="text-blue-300">{fmt(cashBalance)}</span>
            </div>
            <div className="flex justify-between text-[10px] gap-3">
              <span className="text-gray-400">Army Size</span>
              <span className="text-purple-300">{positionsCount} warriors</span>
            </div>
          </div>
        </div>
      </Html>
    </group>
  );
}
