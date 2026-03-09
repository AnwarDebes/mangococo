"use client";

import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import { Line } from "@react-three/drei";
import * as THREE from "three";

interface SignalBeamProps {
  from: [number, number, number];
  to: [number, number, number];
  color: string;
  onComplete: () => void;
}

/** Animated arc beam — like a cyber attack map projectile */
export default function SignalBeam({ from, to, color, onComplete }: SignalBeamProps) {
  const progressRef = useRef(0);
  const headRef = useRef<THREE.Mesh>(null);
  const completedRef = useRef(false);

  const curve = useMemo(() => {
    const start = new THREE.Vector3(...from);
    const end = new THREE.Vector3(...to);
    const mid = new THREE.Vector3().addVectors(start, end).multiplyScalar(0.5);
    mid.y += 8;
    return new THREE.QuadraticBezierCurve3(start, mid, end);
  }, [from, to]);

  const allPoints = useMemo(
    () => curve.getPoints(50).map((p): [number, number, number] => [p.x, p.y, p.z]),
    [curve]
  );

  const trailPointsRef = useRef<[number, number, number][]>([allPoints[0]]);
  const headPosRef = useRef(new THREE.Vector3(...from));

  useFrame((_, delta) => {
    if (completedRef.current) return;
    progressRef.current += delta * 0.8;
    const t = Math.min(progressRef.current, 1);

    // Update trail
    const endIdx = Math.floor(t * (allPoints.length - 1));
    const startIdx = Math.max(0, endIdx - 20); // trail length
    trailPointsRef.current = allPoints.slice(startIdx, endIdx + 1);

    // Update head position
    curve.getPoint(t, headPosRef.current);
    if (headRef.current) {
      headRef.current.position.copy(headPosRef.current);
      // Pulse the head
      const pulse = 1 + Math.sin(progressRef.current * 20) * 0.3;
      headRef.current.scale.setScalar(pulse);
    }

    if (t >= 1 && !completedRef.current) {
      completedRef.current = true;
      onComplete();
    }
  });

  return (
    <group>
      {/* Trail line */}
      {trailPointsRef.current.length > 1 && (
        <Line
          points={trailPointsRef.current}
          color={color}
          lineWidth={2}
          transparent
          opacity={0.7}
        />
      )}

      {/* Glowing head projectile */}
      <mesh ref={headRef}>
        <sphereGeometry args={[0.15, 8, 8]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={2} />
      </mesh>

      {/* Head glow aura */}
      <mesh ref={headRef}>
        <sphereGeometry args={[0.35, 8, 8]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={0.5}
          transparent
          opacity={0.15}
        />
      </mesh>
    </group>
  );
}
