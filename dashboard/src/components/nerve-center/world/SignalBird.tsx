"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import type { Group } from "three";
import type { Signal } from "@/types";

interface SignalBirdProps {
  signal: Signal;
  index: number;
  total: number;
}

export default function SignalBird({ signal, index, total }: SignalBirdProps) {
  const groupRef = useRef<Group>(null);
  const angleRef = useRef((index / Math.max(total, 1)) * Math.PI * 2);

  const color =
    signal.action === "BUY" ? "#22c55e" : signal.action === "SELL" ? "#ef4444" : "#f59e0b";

  const orbitRadius = 12 + (index % 3) * 2;
  const speed = 0.3 + (index % 5) * 0.05;
  const yBase = 6 + Math.sin(index * 2.1) * 3;

  useFrame((_, delta) => {
    if (!groupRef.current) return;
    angleRef.current += delta * speed;
    const a = angleRef.current;
    groupRef.current.position.x = Math.cos(a) * orbitRadius;
    groupRef.current.position.z = Math.sin(a) * orbitRadius;
    groupRef.current.position.y = yBase + Math.sin(a * 2) * 1.5;
    // Face direction of travel
    groupRef.current.rotation.y = -a + Math.PI / 2;
  });

  return (
    <group ref={groupRef}>
      {/* Bird body */}
      <mesh>
        <coneGeometry args={[0.12, 0.4, 4]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.5} />
      </mesh>
      {/* Wings */}
      <mesh position={[-0.15, 0, 0]} rotation={[0, 0, 0.5]}>
        <boxGeometry args={[0.25, 0.02, 0.12]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.3} transparent opacity={0.7} />
      </mesh>
      <mesh position={[0.15, 0, 0]} rotation={[0, 0, -0.5]}>
        <boxGeometry args={[0.25, 0.02, 0.12]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.3} transparent opacity={0.7} />
      </mesh>
      {/* Trail glow */}
      <mesh position={[0, -0.3, 0]}>
        <sphereGeometry args={[0.06, 6, 6]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={1} transparent opacity={0.4} />
      </mesh>

      {/* Label */}
      <Html position={[0, 0.5, 0]} distanceFactor={10} center style={{ pointerEvents: "none" }}>
        <div className="bg-black/80 backdrop-blur rounded px-1.5 py-0.5 border border-white/10 whitespace-nowrap">
          <span className="text-[9px] font-bold" style={{ color }}>
            {signal.action}
          </span>
          <span className="text-[9px] text-gray-300 ml-1">{signal.symbol}</span>
          <span className="text-[9px] text-gray-500 ml-1">{Math.round(signal.confidence * 100)}%</span>
        </div>
      </Html>
    </group>
  );
}
