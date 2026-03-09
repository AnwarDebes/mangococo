"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import type { Group } from "three";

interface FloatingIslandProps {
  position: [number, number, number];
  radius?: number;
  height?: number;
  color?: string;
  glowColor?: string;
  children?: React.ReactNode;
  label?: string;
}

export default function FloatingIsland({
  position,
  radius = 3,
  height = 0.6,
  color = "#1e293b",
  glowColor = "#3b82f6",
  children,
  label,
}: FloatingIslandProps) {
  const groupRef = useRef<Group>(null);
  const floatRef = useRef(Math.random() * Math.PI * 2);

  useFrame((_, delta) => {
    if (!groupRef.current) return;
    floatRef.current += delta * 0.4;
    groupRef.current.position.y = position[1] + Math.sin(floatRef.current) * 0.15;
  });

  return (
    <group ref={groupRef} position={position}>
      {/* Main island body - flat cylinder */}
      <mesh position={[0, 0, 0]}>
        <cylinderGeometry args={[radius, radius * 1.2, height, 12]} />
        <meshStandardMaterial color={color} roughness={0.8} metalness={0.1} />
      </mesh>

      {/* Bottom stalactite */}
      <mesh position={[0, -height * 1.5, 0]}>
        <coneGeometry args={[radius * 0.6, height * 2.5, 8]} />
        <meshStandardMaterial color="#0f172a" roughness={0.9} />
      </mesh>

      {/* Glow ring around edge */}
      <mesh position={[0, height / 2 + 0.02, 0]} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[radius, 0.04, 8, 24]} />
        <meshStandardMaterial
          color={glowColor}
          emissive={glowColor}
          emissiveIntensity={0.8}
          transparent
          opacity={0.6}
        />
      </mesh>

      {/* Surface glow */}
      <mesh position={[0, height / 2 + 0.01, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[radius * 0.95, 12]} />
        <meshStandardMaterial
          color="#111827"
          emissive={glowColor}
          emissiveIntensity={0.05}
        />
      </mesh>

      {/* Children (goblins, objects, etc.) placed on top */}
      <group position={[0, height / 2 + 0.1, 0]}>{children}</group>
    </group>
  );
}
