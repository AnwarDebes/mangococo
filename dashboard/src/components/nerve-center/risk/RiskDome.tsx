"use client";

import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import type { Mesh } from "three";
import type { Position } from "@/types";
import RiskPulse from "./RiskPulse";

interface RiskDomeProps {
  positions: Position[];
}

export default function RiskDome({ positions }: RiskDomeProps) {
  const meshRef = useRef<Mesh>(null);

  const riskColor = useMemo(() => {
    if (!positions.length) return "#6b7280";
    const losers = positions.filter((p) => p.unrealized_pnl < 0).length;
    const ratio = losers / positions.length;
    if (ratio > 0.6) return "#ef4444";
    if (ratio < 0.3) return "#22c55e";
    return "#6b7280";
  }, [positions]);

  useFrame(({ clock }) => {
    if (!meshRef.current) return;
    const pulse = 1 + Math.sin(clock.elapsedTime * 0.5) * 0.005;
    meshRef.current.scale.set(pulse, pulse, pulse);
  });

  return (
    <group>
      <mesh ref={meshRef}>
        <icosahedronGeometry args={[35, 2]} />
        <meshStandardMaterial
          wireframe
          color={riskColor}
          emissive={riskColor}
          emissiveIntensity={0.1}
          transparent
          opacity={0.08}
        />
      </mesh>
      <RiskPulse riskColor={riskColor} />
    </group>
  );
}
