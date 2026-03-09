"use client";

import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import FloatingIsland from "../world/FloatingIsland";
import GoblinCharacter from "../characters/GoblinCharacter";
import type { ModelStatus } from "@/types";
import type { Mesh } from "three";

interface WizardAcademyZoneProps {
  models: ModelStatus[];
}

/** Arcane circle on the ground */
function ArcaneCircle() {
  const meshRef = useRef<Mesh>(null);

  useFrame(({ clock }) => {
    if (meshRef.current) {
      meshRef.current.rotation.z = clock.elapsedTime * 0.2;
    }
  });

  return (
    <group position={[0, 0.05, 0]} rotation={[Math.PI / 2, 0, 0]}>
      <mesh ref={meshRef}>
        <torusGeometry args={[3.5, 0.03, 4, 32]} />
        <meshStandardMaterial color="#a78bfa" emissive="#a78bfa" emissiveIntensity={0.6} transparent opacity={0.4} />
      </mesh>
      {/* Inner rune ring */}
      <mesh rotation={[0, 0, Math.PI / 6]}>
        <torusGeometry args={[2.5, 0.02, 4, 6]} />
        <meshStandardMaterial color="#8b5cf6" emissive="#8b5cf6" emissiveIntensity={0.4} transparent opacity={0.3} />
      </mesh>
      {/* Rune markers */}
      {[0, 1, 2, 3, 4, 5].map((i) => {
        const a = (i / 6) * Math.PI * 2;
        return (
          <mesh key={i} position={[Math.cos(a) * 3, Math.sin(a) * 3, 0]}>
            <octahedronGeometry args={[0.1]} />
            <meshStandardMaterial color="#c4b5fd" emissive="#c4b5fd" emissiveIntensity={0.8} />
          </mesh>
        );
      })}
    </group>
  );
}

export default function WizardAcademyZone({ models }: WizardAcademyZoneProps) {
  const avgAccuracy = useMemo(() => {
    if (!models.length) return 0;
    return models.reduce((s, m) => s + m.accuracy, 0) / models.length;
  }, [models]);

  const activeCount = models.filter((m) => m.status === "active").length;

  return (
    <FloatingIsland
      position={[-12, 0, 16]}
      radius={5}
      height={0.6}
      color="#1e1b4b"
      glowColor="#a78bfa"
    >
      <ArcaneCircle />

      {/* Wizard goblins for each model */}
      {models.map((model, i) => {
        const count = Math.max(models.length, 1);
        const angle = (i / count) * Math.PI * 2;
        const radius = 2;
        const x = Math.cos(angle) * radius;
        const z = Math.sin(angle) * radius;
        const hpVal = Math.round(model.accuracy * 100);

        return (
          <GoblinCharacter
            key={model.model_name}
            name={model.model_name}
            title="AI Wizard"
            role="wizard"
            outfitColor="#4c1d95"
            status={model.status === "active" ? "online" : model.status === "training" ? "degraded" : "offline"}
            hp={hpVal}
            level={hpVal}
            speechText={
              model.status === "training"
                ? "Studying the ancient scrolls..."
                : `Casting predictions at ${hpVal}% power!`
            }
            metrics={[
              { label: "Accuracy", value: `${hpVal}%`, color: hpVal > 70 ? "#22c55e" : "#f59e0b" },
              { label: "Status", value: model.status, color: model.status === "active" ? "#22c55e" : "#a78bfa" },
            ]}
            position={[x, 0, z]}
            scale={0.75}
          />
        );
      })}

      {/* Academy headmaster label */}
      {models.length > 0 && (
        <GoblinCharacter
          name="Headmaster"
          title="Academy Dean"
          role="wizard"
          outfitColor="#5b21b6"
          status="online"
          hp={Math.round(avgAccuracy * 100)}
          level={99}
          speechText={`${activeCount}/${models.length} wizards active, ${(avgAccuracy * 100).toFixed(0)}% avg power`}
          position={[0, 0, 0]}
          scale={1}
        />
      )}
    </FloatingIsland>
  );
}
