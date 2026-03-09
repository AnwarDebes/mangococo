"use client";

import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

interface DataPacketProps {
  from: [number, number, number];
  to: [number, number, number];
  color: string;
  size?: number;
  speed?: number;
  arcHeight?: number;
  trailLength?: number;
  label?: string;
  onComplete: () => void;
}

/**
 * A beautiful animated data packet that travels along an arc between two points.
 * Features:
 * - Glowing head sphere with pulsing aura
 * - Fading trail of smaller spheres behind it
 * - Spark particles that scatter from the head
 */
export default function DataPacket({
  from,
  to,
  color,
  size = 0.2,
  speed = 0.6,
  arcHeight = 6,
  trailLength = 12,
  onComplete,
}: DataPacketProps) {
  const progressRef = useRef(0);
  const completedRef = useRef(false);
  const headRef = useRef<THREE.Mesh>(null);
  const auraRef = useRef<THREE.Mesh>(null);
  const trailMeshRef = useRef<THREE.InstancedMesh>(null);
  const dummy = useMemo(() => new THREE.Object3D(), []);

  const curve = useMemo(() => {
    const start = new THREE.Vector3(...from);
    const end = new THREE.Vector3(...to);
    const mid = new THREE.Vector3().addVectors(start, end).multiplyScalar(0.5);
    mid.y += arcHeight;
    return new THREE.QuadraticBezierCurve3(start, mid, end);
  }, [from, to, arcHeight]);

  const headPos = useRef(new THREE.Vector3(...from));

  useFrame((_, delta) => {
    if (completedRef.current) return;

    progressRef.current += delta * speed;
    const t = Math.min(progressRef.current, 1);

    // Head position
    curve.getPoint(t, headPos.current);
    if (headRef.current) {
      headRef.current.position.copy(headPos.current);
      // Pulse
      const pulse = 1 + Math.sin(progressRef.current * 25) * 0.3;
      headRef.current.scale.setScalar(size * pulse);
    }
    if (auraRef.current) {
      auraRef.current.position.copy(headPos.current);
      const auraPulse = 1 + Math.sin(progressRef.current * 15) * 0.4;
      auraRef.current.scale.setScalar(size * 3 * auraPulse);
    }

    // Trail particles
    if (trailMeshRef.current) {
      for (let i = 0; i < trailLength; i++) {
        const trailT = Math.max(0, t - (i / trailLength) * 0.15);
        const trailPos = curve.getPoint(trailT);
        const fade = 1 - i / trailLength;
        const trailScale = size * 0.6 * fade;

        dummy.position.copy(trailPos);
        // Slight random scatter for sparkle effect
        dummy.position.x += Math.sin(progressRef.current * 30 + i * 2) * 0.08 * fade;
        dummy.position.y += Math.cos(progressRef.current * 25 + i * 3) * 0.08 * fade;
        dummy.scale.setScalar(Math.max(0.01, trailScale));
        dummy.updateMatrix();
        trailMeshRef.current.setMatrixAt(i, dummy.matrix);
      }
      trailMeshRef.current.instanceMatrix.needsUpdate = true;
    }

    if (t >= 1 && !completedRef.current) {
      completedRef.current = true;
      onComplete();
    }
  });

  return (
    <group>
      {/* Head — bright glowing sphere */}
      <mesh ref={headRef}>
        <sphereGeometry args={[1, 10, 10]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={3}
          toneMapped={false}
        />
      </mesh>

      {/* Aura — soft glow around head */}
      <mesh ref={auraRef}>
        <sphereGeometry args={[1, 8, 8]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={1}
          transparent
          opacity={0.15}
          toneMapped={false}
        />
      </mesh>

      {/* Trail — fading particles behind */}
      <instancedMesh ref={trailMeshRef} args={[undefined, undefined, trailLength]} frustumCulled={false}>
        <sphereGeometry args={[1, 6, 6]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={2}
          transparent
          opacity={0.5}
          toneMapped={false}
        />
      </instancedMesh>
    </group>
  );
}
