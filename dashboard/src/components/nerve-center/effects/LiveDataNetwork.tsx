"use client";

import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { ZONE_CONNECTIONS, getZoneById } from "../zones/ZoneConfig";

/**
 * Persistent flowing particle streams along every zone connection.
 * Each connection has particles continuously flowing in its direction —
 * the kingdom's nervous system always alive.
 *
 * Uses a single InstancedMesh for performance (~120 particles total).
 */

const PARTICLES_PER_CONNECTION = 18;
const TOTAL_PARTICLES = ZONE_CONNECTIONS.length * PARTICLES_PER_CONNECTION;
const ARC_HEIGHT = 4;
const BASE_SPEED = 0.15;

interface ConnectionCurve {
  curve: THREE.QuadraticBezierCurve3;
  color: THREE.Color;
  startIdx: number; // index into instanced mesh
}

const _dummy = new THREE.Object3D();
const _pos = new THREE.Vector3();
const _col = new THREE.Color();

export default function LiveDataNetwork() {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const phaseRef = useRef<Float32Array>(new Float32Array(TOTAL_PARTICLES));
  const speedRef = useRef<Float32Array>(new Float32Array(TOTAL_PARTICLES));

  const connections = useMemo(() => {
    const result: ConnectionCurve[] = [];
    let idx = 0;

    for (const conn of ZONE_CONNECTIONS) {
      const fromDef = getZoneById(conn.from as any);
      const toDef = getZoneById(conn.to as any);
      if (!fromDef || !toDef) continue;

      const start = new THREE.Vector3(...fromDef.position);
      const end = new THREE.Vector3(...toDef.position);
      start.y += 1.5;
      end.y += 1.5;
      const mid = new THREE.Vector3().addVectors(start, end).multiplyScalar(0.5);
      mid.y += ARC_HEIGHT;

      const curve = new THREE.QuadraticBezierCurve3(start, mid, end);
      result.push({ curve, color: new THREE.Color(conn.color), startIdx: idx });

      // Initialize phases (evenly distributed along curve)
      for (let i = 0; i < PARTICLES_PER_CONNECTION; i++) {
        phaseRef.current[idx + i] = i / PARTICLES_PER_CONNECTION;
        // Slight speed variation for organic feel
        speedRef.current[idx + i] = BASE_SPEED + (Math.random() - 0.5) * 0.06;
      }
      idx += PARTICLES_PER_CONNECTION;
    }
    return result;
  }, []);

  // Color initialization flag
  const colorsSetRef = useRef(false);

  useFrame((_, delta) => {
    if (!meshRef.current) return;

    // Set colors on first frame
    if (!colorsSetRef.current) {
      colorsSetRef.current = true;
      for (const conn of connections) {
        for (let i = 0; i < PARTICLES_PER_CONNECTION; i++) {
          meshRef.current.setColorAt(conn.startIdx + i, conn.color);
        }
      }
      const ic = meshRef.current.instanceColor;
      if (ic) ic.needsUpdate = true;
    }

    for (const conn of connections) {
      for (let i = 0; i < PARTICLES_PER_CONNECTION; i++) {
        const globalIdx = conn.startIdx + i;
        // Advance phase
        phaseRef.current[globalIdx] += speedRef.current[globalIdx] * delta;
        if (phaseRef.current[globalIdx] > 1) phaseRef.current[globalIdx] -= 1;

        const t = phaseRef.current[globalIdx];

        // Get position on curve
        conn.curve.getPoint(t, _pos);

        // Scale: fade in at start, fade out at end, pulse in middle
        const fade = Math.sin(t * Math.PI); // 0 at edges, 1 in middle
        const pulse = 0.04 + fade * 0.06;

        _dummy.position.copy(_pos);
        _dummy.scale.setScalar(pulse);
        _dummy.updateMatrix();
        meshRef.current.setMatrixAt(globalIdx, _dummy.matrix);
      }
    }
    meshRef.current.instanceMatrix.needsUpdate = true;
  });

  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, TOTAL_PARTICLES]} frustumCulled={false}>
      <sphereGeometry args={[1, 6, 6]} />
      <meshStandardMaterial
        color="white"
        emissive="white"
        emissiveIntensity={1.5}
        transparent
        opacity={0.8}
        toneMapped={false}
      />
    </instancedMesh>
  );
}
