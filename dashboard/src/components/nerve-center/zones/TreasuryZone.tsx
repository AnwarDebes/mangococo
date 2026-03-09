"use client";

import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import TreasureVault from "../world/TreasureVault";
import PositionWarrior from "../characters/PositionWarrior";
import FloatingIsland from "../world/FloatingIsland";
import type { PortfolioState, Position } from "@/types";
import * as THREE from "three";

interface TreasuryZoneProps {
  portfolio?: PortfolioState;
  positions: Position[];
}

/** Coin fountain particles around the treasury */
function CoinFountain() {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const count = 30;
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const particles = useMemo(() => {
    return Array.from({ length: count }, (_, i) => ({
      angle: (i / count) * Math.PI * 2,
      speed: 0.3 + Math.random() * 0.4,
      radius: 2.5 + Math.random() * 1.5,
      yOffset: Math.random() * Math.PI * 2,
      scale: 0.04 + Math.random() * 0.03,
    }));
  }, []);

  useFrame(({ clock }) => {
    if (!meshRef.current) return;
    const t = clock.elapsedTime;
    for (let i = 0; i < count; i++) {
      const p = particles[i];
      const a = p.angle + t * p.speed;
      dummy.position.set(
        Math.cos(a) * p.radius,
        2 + Math.sin(t * 2 + p.yOffset) * 1.5 + Math.sin(a * 3) * 0.5,
        Math.sin(a) * p.radius
      );
      dummy.scale.setScalar(p.scale);
      dummy.rotation.y = t + i;
      dummy.updateMatrix();
      meshRef.current.setMatrixAt(i, dummy.matrix);
    }
    meshRef.current.instanceMatrix.needsUpdate = true;
  });

  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, count]}>
      <cylinderGeometry args={[0.8, 0.8, 0.15, 8]} />
      <meshStandardMaterial
        color="#fbbf24"
        emissive="#f59e0b"
        emissiveIntensity={0.6}
        metalness={0.9}
        roughness={0.1}
      />
    </instancedMesh>
  );
}

export default function TreasuryZone({ portfolio, positions }: TreasuryZoneProps) {
  return (
    <FloatingIsland
      position={[0, 0, 0]}
      radius={5}
      height={0.8}
      color="#1c1917"
      glowColor="#f59e0b"
    >
      <TreasureVault
        totalValue={portfolio?.total_value ?? 0}
        dailyPnl={portfolio?.daily_pnl ?? 0}
        cashBalance={portfolio?.cash_balance ?? 0}
        positionsCount={positions.length}
      />
      <CoinFountain />
      {/* Small position warrior preview */}
      {positions.slice(0, 4).map((pos, i) => (
        <PositionWarrior
          key={pos.symbol + i}
          position={pos}
          index={i}
          total={Math.min(positions.length, 4)}
        />
      ))}
    </FloatingIsland>
  );
}
