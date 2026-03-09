"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import type { Group } from "three";

/* ── Role types ─────────────────────────────────────────────────── */
export type GoblinRole =
  | "wizard"
  | "guardian"
  | "merchant"
  | "scout"
  | "oracle"
  | "treasurer"
  | "warrior";

export interface GoblinMetric {
  label: string;
  value: string;
  color?: string;
}

export interface GoblinProps {
  name: string;
  title: string;
  role: GoblinRole;
  outfitColor: string;
  status: "online" | "degraded" | "offline" | "unknown";
  hp: number;
  level?: number;
  speechText?: string;
  metrics?: GoblinMetric[];
  position?: [number, number, number];
  onClick?: () => void;
  scale?: number;
}

/* ── Skin palette ───────────────────────────────────────────────── */
const SKIN = "#6dd676";
const SKIN_DARK = "#4abe54";

/* ── Role-specific accessory ────────────────────────────────────── */
function Accessory({ role }: { role: GoblinRole }) {
  switch (role) {
    case "wizard":
      return (
        <group position={[0, 1.65, 0]}>
          <mesh>
            <coneGeometry args={[0.28, 0.55, 6]} />
            <meshStandardMaterial color="#7c3aed" emissive="#7c3aed" emissiveIntensity={0.3} />
          </mesh>
          <mesh position={[0, -0.22, 0]} rotation={[Math.PI / 2, 0, 0]}>
            <torusGeometry args={[0.28, 0.04, 4, 12]} />
            <meshStandardMaterial color="#6d28d9" />
          </mesh>
          {/* Staff */}
          <mesh position={[-0.55, -0.45, 0]}>
            <cylinderGeometry args={[0.02, 0.02, 1.4, 6]} />
            <meshStandardMaterial color="#78350f" />
          </mesh>
          <mesh position={[-0.55, 0.3, 0]}>
            <octahedronGeometry args={[0.1]} />
            <meshStandardMaterial color="#a78bfa" emissive="#a78bfa" emissiveIntensity={0.8} />
          </mesh>
        </group>
      );
    case "guardian":
      return (
        <group>
          <mesh position={[0, 1.55, 0]}>
            <sphereGeometry args={[0.3, 8, 6, 0, Math.PI * 2, 0, Math.PI / 2]} />
            <meshStandardMaterial color="#94a3b8" metalness={0.8} roughness={0.2} />
          </mesh>
          {/* Shield */}
          <mesh position={[0.5, 0.7, 0.1]} rotation={[0, -0.3, 0]}>
            <circleGeometry args={[0.28, 6]} />
            <meshStandardMaterial color="#dc2626" emissive="#dc2626" emissiveIntensity={0.2} side={2} />
          </mesh>
          {/* Sword */}
          <mesh position={[-0.45, 0.8, 0]} rotation={[0, 0, 0.2]}>
            <boxGeometry args={[0.04, 0.65, 0.02]} />
            <meshStandardMaterial color="#d1d5db" metalness={0.9} roughness={0.1} />
          </mesh>
        </group>
      );
    case "merchant":
      return (
        <group>
          <mesh position={[0, 1.58, 0]}>
            <cylinderGeometry args={[0.15, 0.28, 0.15, 8]} />
            <meshStandardMaterial color="#92400e" />
          </mesh>
          <mesh position={[-0.4, 0.5, 0.1]}>
            <boxGeometry args={[0.2, 0.25, 0.15]} />
            <meshStandardMaterial color="#78350f" />
          </mesh>
        </group>
      );
    case "oracle":
      return (
        <group>
          <mesh position={[0, 1.55, -0.05]}>
            <sphereGeometry args={[0.32, 8, 8, 0, Math.PI * 2, 0, Math.PI * 0.6]} />
            <meshStandardMaterial color="#155e75" transparent opacity={0.8} />
          </mesh>
          <mesh position={[0.45, 1.1, 0.2]}>
            <sphereGeometry args={[0.12, 12, 12]} />
            <meshStandardMaterial
              color="#06b6d4"
              emissive="#06b6d4"
              emissiveIntensity={0.8}
              transparent
              opacity={0.7}
            />
          </mesh>
        </group>
      );
    case "treasurer":
      return (
        <group>
          <mesh position={[0, 1.6, 0]}>
            <torusGeometry args={[0.22, 0.05, 4, 6]} />
            <meshStandardMaterial
              color="#fbbf24"
              metalness={0.9}
              roughness={0.1}
              emissive="#f59e0b"
              emissiveIntensity={0.4}
            />
          </mesh>
          {[0, 1.25, 2.5, 3.75, 5].map((a, i) => (
            <mesh key={i} position={[Math.cos(a) * 0.22, 1.68, Math.sin(a) * 0.22]}>
              <coneGeometry args={[0.04, 0.12, 4]} />
              <meshStandardMaterial color="#fbbf24" metalness={0.9} roughness={0.1} />
            </mesh>
          ))}
        </group>
      );
    case "scout":
      return (
        <group>
          <mesh position={[0, 1.5, 0.15]} rotation={[0.2, 0, 0]}>
            <boxGeometry args={[0.5, 0.08, 0.5]} />
            <meshStandardMaterial color="#1d4ed8" />
          </mesh>
          <mesh position={[0.4, 1.0, 0.15]} rotation={[0, 0, 0.5]}>
            <cylinderGeometry args={[0.03, 0.06, 0.4, 8]} />
            <meshStandardMaterial color="#78350f" />
          </mesh>
        </group>
      );
    case "warrior":
      return (
        <group>
          <mesh position={[0, 1.55, 0]}>
            <sphereGeometry args={[0.3, 8, 6, 0, Math.PI * 2, 0, Math.PI / 2]} />
            <meshStandardMaterial color="#71717a" metalness={0.7} roughness={0.3} />
          </mesh>
          {/* Horns */}
          <mesh position={[-0.25, 1.7, 0]} rotation={[0, 0, -0.5]}>
            <coneGeometry args={[0.04, 0.2, 4]} />
            <meshStandardMaterial color="#e5e5e5" />
          </mesh>
          <mesh position={[0.25, 1.7, 0]} rotation={[0, 0, 0.5]}>
            <coneGeometry args={[0.04, 0.2, 4]} />
            <meshStandardMaterial color="#e5e5e5" />
          </mesh>
          <mesh position={[0.45, 0.7, 0]} rotation={[0, 0, -0.2]}>
            <boxGeometry args={[0.04, 0.7, 0.02]} />
            <meshStandardMaterial color="#d1d5db" metalness={0.9} roughness={0.1} />
          </mesh>
          <mesh position={[0.45, 0.32, 0]}>
            <boxGeometry args={[0.15, 0.04, 0.04]} />
            <meshStandardMaterial color="#78350f" />
          </mesh>
        </group>
      );
    default:
      return null;
  }
}

/* ── Main GoblinCharacter component ─────────────────────────────── */
export default function GoblinCharacter({
  name,
  title,
  role,
  outfitColor,
  status,
  hp,
  level,
  speechText,
  metrics,
  position: pos = [0, 0, 0],
  onClick,
  scale: s = 1,
}: GoblinProps) {
  const groupRef = useRef<Group>(null);
  const bobRef = useRef(Math.random() * Math.PI * 2);

  const statusColor =
    status === "online"
      ? "#22c55e"
      : status === "degraded"
        ? "#f59e0b"
        : status === "offline"
          ? "#ef4444"
          : "#6b7280";

  useFrame((_, delta) => {
    if (!groupRef.current) return;
    bobRef.current += delta * 1.5;
    groupRef.current.position.y = pos[1] + Math.sin(bobRef.current) * 0.06;
  });

  return (
    <group ref={groupRef} position={pos} scale={s} onClick={onClick}>
      {/* Platform pedestal */}
      <mesh position={[0, -0.05, 0]}>
        <cylinderGeometry args={[0.8, 1, 0.12, 8]} />
        <meshStandardMaterial color="#374151" metalness={0.3} roughness={0.7} />
      </mesh>
      {/* Status glow ring */}
      <mesh position={[0, 0.02, 0]} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[0.9, 0.04, 8, 24]} />
        <meshStandardMaterial color={statusColor} emissive={statusColor} emissiveIntensity={1.2} />
      </mesh>

      {/* ── BODY ── */}
      {/* Legs */}
      <mesh position={[-0.12, 0.2, 0]}>
        <capsuleGeometry args={[0.06, 0.2, 4, 8]} />
        <meshStandardMaterial color={SKIN_DARK} />
      </mesh>
      <mesh position={[0.12, 0.2, 0]}>
        <capsuleGeometry args={[0.06, 0.2, 4, 8]} />
        <meshStandardMaterial color={SKIN_DARK} />
      </mesh>

      {/* Torso */}
      <mesh position={[0, 0.65, 0]}>
        <capsuleGeometry args={[0.22, 0.3, 4, 8]} />
        <meshStandardMaterial color={outfitColor} />
      </mesh>

      {/* Arms */}
      <mesh position={[-0.35, 0.65, 0]} rotation={[0, 0, 0.3]}>
        <capsuleGeometry args={[0.06, 0.25, 4, 8]} />
        <meshStandardMaterial color={SKIN} />
      </mesh>
      <mesh position={[0.35, 0.65, 0]} rotation={[0, 0, -0.3]}>
        <capsuleGeometry args={[0.06, 0.25, 4, 8]} />
        <meshStandardMaterial color={SKIN} />
      </mesh>

      {/* Head */}
      <mesh position={[0, 1.15, 0]}>
        <sphereGeometry args={[0.3, 12, 12]} />
        <meshStandardMaterial color={SKIN} />
      </mesh>

      {/* Ears */}
      <mesh position={[-0.35, 1.25, 0]} rotation={[0, 0, -0.8]}>
        <coneGeometry args={[0.06, 0.25, 4]} />
        <meshStandardMaterial color={SKIN} />
      </mesh>
      <mesh position={[0.35, 1.25, 0]} rotation={[0, 0, 0.8]}>
        <coneGeometry args={[0.06, 0.25, 4]} />
        <meshStandardMaterial color={SKIN} />
      </mesh>

      {/* Eyes */}
      <mesh position={[-0.1, 1.2, 0.25]}>
        <sphereGeometry args={[0.06, 8, 8]} />
        <meshStandardMaterial color="white" />
      </mesh>
      <mesh position={[0.1, 1.2, 0.25]}>
        <sphereGeometry args={[0.06, 8, 8]} />
        <meshStandardMaterial color="white" />
      </mesh>
      <mesh position={[-0.1, 1.2, 0.3]}>
        <sphereGeometry args={[0.03, 8, 8]} />
        <meshStandardMaterial color="#1a1a2e" />
      </mesh>
      <mesh position={[0.1, 1.2, 0.3]}>
        <sphereGeometry args={[0.03, 8, 8]} />
        <meshStandardMaterial color="#1a1a2e" />
      </mesh>

      {/* Nose */}
      <mesh position={[0, 1.12, 0.3]}>
        <sphereGeometry args={[0.05, 6, 6]} />
        <meshStandardMaterial color={SKIN_DARK} />
      </mesh>

      {/* Mouth — little grin */}
      <mesh position={[0, 1.05, 0.28]} rotation={[0.2, 0, 0]}>
        <torusGeometry args={[0.06, 0.012, 4, 8, Math.PI]} />
        <meshStandardMaterial color="#2d5a30" />
      </mesh>

      {/* Role accessory */}
      <Accessory role={role} />

      {/* ── HTML OVERLAY ── */}
      <Html position={[0, 2.4, 0]} distanceFactor={7} center style={{ pointerEvents: "none" }}>
        <div className="flex flex-col items-center gap-1 select-none" style={{ minWidth: 170 }}>
          {/* Speech bubble */}
          {speechText && (
            <div className="bg-gray-900/90 backdrop-blur border border-amber-500/30 rounded-xl px-3 py-1.5 mb-0.5 relative">
              <p className="text-[11px] text-gray-100 text-center leading-tight max-w-[190px]">
                {speechText}
              </p>
              {/* Bubble tail */}
              <div
                className="absolute -bottom-1.5 left-1/2 -translate-x-1/2 w-0 h-0"
                style={{
                  borderLeft: "5px solid transparent",
                  borderRight: "5px solid transparent",
                  borderTop: "6px solid rgba(17,24,39,0.9)",
                }}
              />
            </div>
          )}

          {/* Name plate */}
          <div className="bg-black/85 backdrop-blur border border-white/15 rounded-md px-2.5 py-1">
            <div className="flex items-center gap-1.5 justify-center">
              <span
                className="w-2 h-2 rounded-full shrink-0 animate-pulse"
                style={{ backgroundColor: statusColor }}
              />
              <span className="text-sm font-bold text-white">{name}</span>
              {level != null && (
                <span className="text-[10px] text-yellow-400 font-bold bg-yellow-400/10 rounded px-1">
                  Lv.{level}
                </span>
              )}
            </div>
            <div className="text-[10px] text-gray-400 text-center italic">{title}</div>
          </div>

          {/* HP Bar */}
          <div className="w-full px-1">
            <div className="flex items-center gap-1">
              <span className="text-[9px] text-red-400 font-bold w-5">HP</span>
              <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden border border-gray-600">
                <div
                  className="h-full rounded-full transition-all duration-700"
                  style={{
                    width: `${Math.min(100, Math.max(0, hp))}%`,
                    backgroundColor:
                      hp > 70 ? "#22c55e" : hp > 40 ? "#f59e0b" : "#ef4444",
                    boxShadow:
                      hp > 70
                        ? "0 0 6px #22c55e"
                        : hp > 40
                          ? "0 0 6px #f59e0b"
                          : "0 0 6px #ef4444",
                  }}
                />
              </div>
              <span className="text-[9px] text-gray-300 w-7 text-right">{Math.round(hp)}%</span>
            </div>
          </div>

          {/* Metrics */}
          {metrics && metrics.length > 0 && (
            <div className="bg-black/70 backdrop-blur rounded-md px-2 py-1 w-full border border-white/5">
              {metrics.map((m, i) => (
                <div key={i} className="flex justify-between text-[10px] gap-2">
                  <span className="text-gray-400">{m.label}</span>
                  <span style={{ color: m.color ?? "#e5e7eb" }} className="font-medium">
                    {m.value}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </Html>
    </group>
  );
}
