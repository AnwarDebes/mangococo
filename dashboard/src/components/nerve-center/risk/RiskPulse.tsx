"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import type { Mesh, MeshStandardMaterial } from "three";

interface RiskPulseProps {
  riskColor: string;
}

export default function RiskPulse({ riskColor }: RiskPulseProps) {
  const meshRef = useRef<Mesh>(null);
  const scaleRef = useRef(1);

  useFrame((_, delta) => {
    if (!meshRef.current) return;
    scaleRef.current += delta * 5;
    if (scaleRef.current > 35) scaleRef.current = 1;

    const opacity = Math.max(0, 0.15 * (1 - scaleRef.current / 35));
    meshRef.current.scale.set(scaleRef.current, scaleRef.current, scaleRef.current);

    const mat = meshRef.current.material as MeshStandardMaterial;
    if (mat) mat.opacity = opacity;
  });

  return (
    <mesh ref={meshRef}>
      <torusGeometry args={[1, 0.02, 8, 64]} />
      <meshStandardMaterial
        color={riskColor}
        emissive={riskColor}
        emissiveIntensity={0.5}
        transparent
        opacity={0.15}
      />
    </mesh>
  );
}
