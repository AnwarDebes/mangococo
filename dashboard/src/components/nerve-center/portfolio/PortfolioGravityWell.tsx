"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import type { Mesh } from "three";
import PositionOrbit from "./PositionOrbit";
import type { PortfolioState, Position } from "@/types";

interface PortfolioGravityWellProps {
  portfolio?: PortfolioState;
  positions: Position[];
}

const CENTER_X = -20;

export default function PortfolioGravityWell({ portfolio, positions }: PortfolioGravityWellProps) {
  const coreRef = useRef<Mesh>(null);
  const totalValue = portfolio?.total_value ?? 0;
  const coreSize = totalValue > 0 ? Math.max(1, Math.log10(totalValue) * 0.5) : 1;

  useFrame(({ clock }) => {
    if (!coreRef.current) return;
    const pulse = 1 + Math.sin(clock.elapsedTime * 1.5) * 0.03;
    coreRef.current.scale.set(pulse, pulse, pulse);
  });

  return (
    <group position={[CENTER_X, 0, 0]}>
      {/* Central mass */}
      <mesh ref={coreRef}>
        <sphereGeometry args={[coreSize, 32, 32]} />
        <meshStandardMaterial
          color="#3b82f6"
          emissive="#3b82f6"
          emissiveIntensity={0.7}
          transparent
          opacity={0.8}
        />
      </mesh>

      {/* Value label */}
      <Html distanceFactor={20} position={[0, coreSize + 1, 0]} style={{ pointerEvents: "none" }}>
        <div className="text-center whitespace-nowrap select-none">
          <div className="text-sm font-bold text-blue-400">
            ${totalValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </div>
          <div className="text-[10px] text-gray-400">Portfolio Value</div>
        </div>
      </Html>

      {/* Orbiting positions */}
      {positions.map((pos, i) => {
        const posValue = pos.amount * pos.current_price;
        const orbitRadius = totalValue > 0
          ? 2 + (posValue / totalValue) * 8
          : 3 + i;
        const openedRecently = Date.now() - new Date(pos.opened_at).getTime() < 86400000;
        const orbitSpeed = openedRecently ? 1.5 : 0.5;

        return (
          <PositionOrbit
            key={pos.symbol + i}
            position={pos}
            orbitRadius={orbitRadius}
            orbitSpeed={orbitSpeed}
            index={i}
            centerX={0}
          />
        );
      })}
    </group>
  );
}
