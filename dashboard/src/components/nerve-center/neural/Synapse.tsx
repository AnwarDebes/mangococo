"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Line } from "@react-three/drei";
import * as THREE from "three";

interface SynapseProps {
  start: [number, number, number];
  end: [number, number, number];
  active: boolean;
  color: string;
  speed?: number;
}

export default function Synapse({ start, end, active, color, speed = 1 }: SynapseProps) {
  const pulseRef = useRef<THREE.Mesh>(null);
  const tRef = useRef(0);
  const midVec = useRef(new THREE.Vector3());

  const midPoint: [number, number, number] = [
    (start[0] + end[0]) / 2,
    (start[1] + end[1]) / 2 + 1,
    (start[2] + end[2]) / 2,
  ];

  useFrame((_, delta) => {
    if (!pulseRef.current || !active) return;
    tRef.current = (tRef.current + delta * speed * 0.5) % 1;
    const t = tRef.current;
    const oneMinusT = 1 - t;

    pulseRef.current.position.set(
      oneMinusT * oneMinusT * start[0] + 2 * oneMinusT * t * midPoint[0] + t * t * end[0],
      oneMinusT * oneMinusT * start[1] + 2 * oneMinusT * t * midPoint[1] + t * t * end[1],
      oneMinusT * oneMinusT * start[2] + 2 * oneMinusT * t * midPoint[2] + t * t * end[2],
    );
  });

  return (
    <group>
      <Line
        points={[start, midPoint, end]}
        color={color}
        lineWidth={active ? 1.5 : 0.5}
        opacity={active ? 0.6 : 0.15}
        transparent
      />
      {active && (
        <mesh ref={pulseRef}>
          <sphereGeometry args={[0.08, 8, 8]} />
          <meshStandardMaterial color={color} emissive={color} emissiveIntensity={2} />
        </mesh>
      )}
    </group>
  );
}
