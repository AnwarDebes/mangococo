"use client";

import { useRef, useState } from "react";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import type { Mesh } from "three";
import type { Position } from "@/types";
import { useNerveCenterStore } from "../NerveCenterStore";
import PnLTrail from "./PnLTrail";

interface PositionOrbitProps {
  position: Position;
  orbitRadius: number;
  orbitSpeed: number;
  index: number;
  centerX: number;
}

export default function PositionOrbit({ position, orbitRadius, orbitSpeed, index, centerX }: PositionOrbitProps) {
  const meshRef = useRef<Mesh>(null);
  const angleRef = useRef(index * 1.2);
  const [hovered, setHovered] = useState(false);
  const selectPosition = useNerveCenterStore((s) => s.selectPosition);

  const isProfitable = position.unrealized_pnl >= 0;
  const color = isProfitable ? "#22c55e" : "#ef4444";
  const yOffset = isProfitable ? 1 + Math.abs(position.unrealized_pnl) * 0.01 : -1 - Math.abs(position.unrealized_pnl) * 0.01;
  const posSize = Math.max(0.2, Math.min(0.8, Math.log10((position.amount * position.current_price) + 1) * 0.2));

  useFrame((_, delta) => {
    if (!meshRef.current) return;
    angleRef.current += orbitSpeed * delta;
    meshRef.current.position.x = centerX + Math.cos(angleRef.current) * orbitRadius;
    meshRef.current.position.z = Math.sin(angleRef.current) * orbitRadius;
    meshRef.current.position.y = Math.min(Math.max(yOffset, -3), 3);
  });

  return (
    <mesh
      ref={meshRef}
      onPointerOver={() => setHovered(true)}
      onPointerOut={() => setHovered(false)}
      onClick={() => selectPosition(position.symbol)}
      scale={hovered ? 1.3 : 1}
    >
      <sphereGeometry args={[posSize, 16, 16]} />
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={0.6}
        transparent
        opacity={0.9}
      />

      <PnLTrail color={color} radius={posSize * 1.5} />

      {hovered && (
        <Html distanceFactor={10} style={{ pointerEvents: "none" }}>
          <div className="bg-gray-900/95 border border-goblin-500/30 rounded-lg p-3 w-52 backdrop-blur text-white">
            <div className="font-bold text-sm mb-1">{position.symbol}</div>
            <div className="space-y-0.5 text-xs text-gray-300">
              <div className="flex justify-between">
                <span>Side</span>
                <span className={position.side === "long" ? "text-green-400" : "text-red-400"}>
                  {position.side}
                </span>
              </div>
              <div className="flex justify-between">
                <span>Entry</span>
                <span>${position.entry_price.toLocaleString()}</span>
              </div>
              <div className="flex justify-between">
                <span>Current</span>
                <span>${position.current_price.toLocaleString()}</span>
              </div>
              <div className="flex justify-between">
                <span>Unrealized P&L</span>
                <span className={isProfitable ? "text-green-400" : "text-red-400"}>
                  ${position.unrealized_pnl.toFixed(2)}
                </span>
              </div>
              {(position.stop_loss_price ?? 0) > 0 && (
                <div className="flex justify-between">
                  <span>Stop Loss</span>
                  <span className="text-red-400">${position.stop_loss_price!.toLocaleString()}</span>
                </div>
              )}
              {(position.take_profit_price ?? 0) > 0 && (
                <div className="flex justify-between">
                  <span>Take Profit</span>
                  <span className="text-green-400">${position.take_profit_price!.toLocaleString()}</span>
                </div>
              )}
            </div>
          </div>
        </Html>
      )}
    </mesh>
  );
}
