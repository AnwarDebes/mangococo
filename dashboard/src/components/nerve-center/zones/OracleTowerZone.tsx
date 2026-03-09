"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import FloatingIsland from "../world/FloatingIsland";
import SignalBird from "../world/SignalBird";
import GoblinCharacter from "../characters/GoblinCharacter";
import type { Signal } from "@/types";
import type { Group, Mesh, MeshStandardMaterial } from "three";

interface OracleTowerZoneProps {
  signals: Signal[];
}

/** Crystal tower structure */
function CrystalTower() {
  const topRef = useRef<Mesh>(null);
  const groupRef = useRef<Group>(null);

  useFrame(({ clock }) => {
    if (topRef.current) {
      topRef.current.rotation.y = clock.elapsedTime * 0.5;
      const pulse = 1 + Math.sin(clock.elapsedTime * 2) * 0.05;
      topRef.current.scale.set(pulse, pulse, pulse);
    }
    if (groupRef.current) {
      groupRef.current.rotation.y = clock.elapsedTime * 0.1;
    }
  });

  return (
    <group>
      {/* Tower base */}
      <mesh position={[0, 0.8, 0]}>
        <cylinderGeometry args={[0.5, 0.8, 1.5, 6]} />
        <meshStandardMaterial color="#155e75" metalness={0.2} roughness={0.8} />
      </mesh>
      {/* Tower mid section */}
      <mesh position={[0, 2, 0]}>
        <cylinderGeometry args={[0.4, 0.5, 1, 6]} />
        <meshStandardMaterial color="#164e63" metalness={0.2} roughness={0.8} />
      </mesh>
      {/* Top crystal */}
      <mesh ref={topRef} position={[0, 3.2, 0]}>
        <octahedronGeometry args={[0.5, 1]} />
        <meshStandardMaterial
          color="#06b6d4"
          emissive="#06b6d4"
          emissiveIntensity={0.8}
          transparent
          opacity={0.7}
        />
      </mesh>
      {/* Orbital rings */}
      <group ref={groupRef} position={[0, 3.2, 0]}>
        <mesh rotation={[Math.PI / 3, 0, 0]}>
          <torusGeometry args={[0.9, 0.015, 8, 24]} />
          <meshStandardMaterial color="#06b6d4" emissive="#06b6d4" emissiveIntensity={0.5} transparent opacity={0.4} />
        </mesh>
        <mesh rotation={[Math.PI / 2, Math.PI / 4, 0]}>
          <torusGeometry args={[1.1, 0.015, 8, 24]} />
          <meshStandardMaterial color="#22d3ee" emissive="#22d3ee" emissiveIntensity={0.5} transparent opacity={0.3} />
        </mesh>
      </group>
      {/* Glow */}
      <mesh position={[0, 3.2, 0]}>
        <sphereGeometry args={[0.8, 12, 12]} />
        <meshStandardMaterial color="#06b6d4" emissive="#06b6d4" emissiveIntensity={0.4} transparent opacity={0.08} />
      </mesh>
    </group>
  );
}

/** Signal counter beacon */
function SignalBeacon({ count }: { count: number }) {
  const meshRef = useRef<Mesh>(null);

  useFrame(({ clock }) => {
    if (!meshRef.current) return;
    const mat = meshRef.current.material as MeshStandardMaterial;
    mat.emissiveIntensity = 0.3 + Math.sin(clock.elapsedTime * 3) * 0.2;
  });

  return (
    <group position={[2, 1.5, 0]}>
      <mesh ref={meshRef}>
        <sphereGeometry args={[0.2, 8, 8]} />
        <meshStandardMaterial color="#22d3ee" emissive="#22d3ee" emissiveIntensity={0.5} />
      </mesh>
      <Html position={[0, 0.5, 0]} distanceFactor={8} center style={{ pointerEvents: "none" }}>
        <div className="bg-cyan-900/80 backdrop-blur rounded-full px-2 py-0.5 border border-cyan-400/30">
          <span className="text-cyan-300 text-[10px] font-bold">{count} signals</span>
        </div>
      </Html>
    </group>
  );
}

export default function OracleTowerZone({ signals }: OracleTowerZoneProps) {
  const buyCount = signals.filter((s) => s.action === "BUY").length;
  const sellCount = signals.filter((s) => s.action === "SELL").length;
  const avgConf = signals.length > 0
    ? signals.reduce((s, sig) => s + sig.confidence, 0) / signals.length
    : 0;

  return (
    <FloatingIsland
      position={[12, 0, 16]}
      radius={5}
      height={0.6}
      color="#164e63"
      glowColor="#06b6d4"
    >
      <CrystalTower />
      <SignalBeacon count={signals.length} />

      {/* Oracle goblin */}
      <GoblinCharacter
        name="Grand Oracle"
        title="Signal Master"
        role="oracle"
        outfitColor="#155e75"
        status="online"
        hp={Math.round(avgConf * 100)}
        level={signals.length}
        speechText={`${buyCount} buy, ${sellCount} sell quests active`}
        metrics={[
          { label: "Avg Power", value: `${(avgConf * 100).toFixed(0)}%`, color: avgConf > 0.7 ? "#22c55e" : "#f59e0b" },
        ]}
        position={[-2, 0, 1]}
        scale={0.9}
      />

      {/* Signal birds orbit this zone */}
      {signals.slice(0, 10).map((sig, i) => (
        <SignalBird key={sig.signal_id} signal={sig} index={i} total={Math.min(signals.length, 10)} />
      ))}
    </FloatingIsland>
  );
}
