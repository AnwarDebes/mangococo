"use client";

import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

interface AmbientMagicProps {
  count?: number;
}

/** Floating magic particles throughout the kingdom using InstancedMesh */
export default function AmbientMagic({ count = 400 }: AmbientMagicProps) {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const dummy = useMemo(() => new THREE.Object3D(), []);

  const particles = useMemo(() => {
    return Array.from({ length: count }, () => ({
      x: (Math.random() - 0.5) * 60,
      y: Math.random() * 15 - 2,
      z: (Math.random() - 0.5) * 60,
      speedY: 0.1 + Math.random() * 0.3,
      driftX: (Math.random() - 0.5) * 0.5,
      driftZ: (Math.random() - 0.5) * 0.5,
      phase: Math.random() * Math.PI * 2,
      scale: 0.02 + Math.random() * 0.04,
    }));
  }, [count]);

  useFrame(({ clock }) => {
    if (!meshRef.current) return;
    const t = clock.elapsedTime;
    for (let i = 0; i < count; i++) {
      const p = particles[i];
      let y = p.y + ((t * p.speedY + p.phase) % 18) - 2;
      if (y > 16) y = -2;
      dummy.position.set(
        p.x + Math.sin(t * 0.3 + p.phase) * p.driftX,
        y,
        p.z + Math.cos(t * 0.4 + p.phase) * p.driftZ
      );
      const flicker = 0.5 + Math.sin(t * 3 + p.phase) * 0.5;
      dummy.scale.setScalar(p.scale * flicker);
      dummy.updateMatrix();
      meshRef.current.setMatrixAt(i, dummy.matrix);
    }
    meshRef.current.instanceMatrix.needsUpdate = true;
  });

  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, count]}>
      <sphereGeometry args={[1, 4, 4]} />
      <meshStandardMaterial
        color="#fbbf24"
        emissive="#f59e0b"
        emissiveIntensity={2}
        transparent
        opacity={0.6}
      />
    </instancedMesh>
  );
}
