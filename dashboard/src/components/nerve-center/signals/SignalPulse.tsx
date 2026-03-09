"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import type { Mesh } from "three";
import { signalColor, tempVec3 } from "@/lib/nerve-center-utils";
import { useNerveCenterStore } from "../NerveCenterStore";
import type { Signal } from "@/types";

interface SignalPulseProps {
  signal: Signal;
  action: string;
  confidence: number;
  targetPosition: [number, number, number];
  onArrive?: () => void;
}

const ORIGIN: [number, number, number] = [0, 10, 0];

export default function SignalPulse({ signal, action, confidence, targetPosition, onArrive }: SignalPulseProps) {
  const meshRef = useRef<Mesh>(null);
  const arrivedRef = useRef(false);
  const selectSignal = useNerveCenterStore((s) => s.selectSignal);

  const color = signalColor(action);
  const size = 0.15 + confidence * 0.25;

  useFrame(() => {
    if (!meshRef.current || arrivedRef.current) return;

    tempVec3.set(...targetPosition);
    meshRef.current.position.lerp(tempVec3, 0.03);

    const dist = meshRef.current.position.distanceTo(tempVec3);
    if (dist < 0.5) {
      arrivedRef.current = true;
      meshRef.current.visible = false;
      onArrive?.();
    }
  });

  return (
    <mesh
      ref={meshRef}
      position={ORIGIN}
      onClick={(e) => {
        e.stopPropagation();
        selectSignal(signal.signal_id);
      }}
    >
      <sphereGeometry args={[size, 12, 12]} />
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={1.5}
      />
    </mesh>
  );
}
