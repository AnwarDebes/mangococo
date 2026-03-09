"use client";

import { useRef, useState, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import type { Mesh } from "three";
import { priceToRadius, sentimentColor } from "@/lib/nerve-center-utils";
import { useNerveCenterStore } from "../NerveCenterStore";
import CryptoNodeLabel from "./CryptoNodeLabel";
import type { TickerPrice } from "@/lib/api";
import type { SentimentData, Signal } from "@/types";

interface CryptoNodeProps {
  ticker: TickerPrice;
  position: [number, number, number];
  sentiment?: SentimentData;
  signal?: Signal;
  index: number;
}

export default function CryptoNode({ ticker, position, sentiment, signal, index }: CryptoNodeProps) {
  const meshRef = useRef<Mesh>(null);
  const ringRef = useRef<Mesh>(null);
  const [hovered, setHovered] = useState(false);
  const selectNode = useNerveCenterStore((s) => s.selectNode);
  const flyTo = useNerveCenterStore((s) => s.flyTo);
  const selectedNode = useNerveCenterStore((s) => s.selectedNode);

  const radius = useMemo(() => priceToRadius(parseFloat(ticker.lastPrice || "0")), [ticker.lastPrice]);
  const color = useMemo(() => sentimentColor(sentiment?.score ?? 50), [sentiment?.score]);
  const changeAbs = Math.abs(parseFloat(ticker.priceChangePercent || "0"));
  const emissiveIntensity = Math.min(changeAbs / 10, 1);
  const isSelected = selectedNode === ticker.symbol;

  // Sentiment momentum drives ring rotation speed
  const momentum = sentiment?.momentum_1h ?? 0;

  useFrame(({ clock }) => {
    if (!meshRef.current) return;
    const breathe = Math.sin(clock.elapsedTime * 1.5 + index * 0.7) * 0.05;
    const baseScale = hovered ? 1.2 : 1;
    const s = baseScale + breathe;
    meshRef.current.scale.set(s, s, s);

    // Rotate sentiment ring based on momentum
    if (ringRef.current) {
      ringRef.current.rotation.z = clock.elapsedTime * (momentum > 0 ? 1 : momentum < 0 ? -0.5 : 0.2);
    }
  });

  return (
    <group position={position}>
      <mesh
        ref={meshRef}
        onClick={(e) => {
          e.stopPropagation();
          selectNode(isSelected ? null : ticker.symbol);
          if (!isSelected) {
            flyTo(
              [position[0], position[1] + 3, position[2] + 5],
              [position[0], position[1], position[2]]
            );
          }
        }}
        onPointerOver={() => setHovered(true)}
        onPointerOut={() => setHovered(false)}
      >
        <sphereGeometry args={[radius, 32, 32]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={emissiveIntensity + (hovered ? 0.3 : 0) + (isSelected ? 0.4 : 0)}
          transparent
          opacity={0.85}
          roughness={0.3}
          metalness={0.2}
        />
      </mesh>

      {/* Sentiment ring */}
      <mesh ref={ringRef} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[radius + 0.4, 0.03, 8, 32]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={0.8}
          transparent
          opacity={0.5}
        />
      </mesh>

      <CryptoNodeLabel
        symbol={ticker.symbol}
        price={ticker.lastPrice}
        change={ticker.priceChangePercent}
        volume={ticker.volume}
        sentimentScore={sentiment?.score}
      />

      {/* Signal indicator orbiting the node */}
      {signal && (
        <SignalIndicator action={signal.action} radius={radius} />
      )}
    </group>
  );
}

function SignalIndicator({ action, radius }: { action: string; radius: number }) {
  const ref = useRef<Mesh>(null);
  const color = action === "BUY" ? "#22c55e" : action === "SELL" ? "#ef4444" : "#f59e0b";

  useFrame(({ clock }) => {
    if (!ref.current) return;
    const t = clock.elapsedTime * 2;
    ref.current.position.x = Math.cos(t) * (radius + 0.5);
    ref.current.position.z = Math.sin(t) * (radius + 0.5);
  });

  return (
    <mesh ref={ref}>
      <sphereGeometry args={[0.12, 16, 16]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={1} />
    </mesh>
  );
}
