"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import type { Mesh, MeshStandardMaterial } from "three";

interface PnLTrailProps {
  color: string;
  radius: number;
}

/** Fading ring trail that expands outward from a position orbit sphere. */
export default function PnLTrail({ color, radius }: PnLTrailProps) {
  const meshRef = useRef<Mesh>(null);
  const scaleRef = useRef(0.3);

  useFrame((_, delta) => {
    if (!meshRef.current) return;
    scaleRef.current += delta * 1.2;
    if (scaleRef.current > 3) scaleRef.current = 0.3;

    const progress = (scaleRef.current - 0.3) / 2.7;
    const opacity = Math.max(0, 0.3 * (1 - progress));

    meshRef.current.scale.set(scaleRef.current, scaleRef.current, scaleRef.current);
    const mat = meshRef.current.material as MeshStandardMaterial;
    if (mat) mat.opacity = opacity;
  });

  return (
    <mesh ref={meshRef} rotation={[Math.PI / 2, 0, 0]}>
      <torusGeometry args={[radius, 0.01, 6, 32]} />
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={0.4}
        transparent
        opacity={0.3}
      />
    </mesh>
  );
}
