"use client";

import { useRef, useState } from "react";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import type { Mesh } from "three";
import type { ModelStatus } from "@/types";

interface NeuronNodeProps {
  model: ModelStatus;
  position: [number, number, number];
  isCore?: boolean;
}

export default function NeuronNode({ model, position, isCore = false }: NeuronNodeProps) {
  const meshRef = useRef<Mesh>(null);
  const [clicked, setClicked] = useState(false);

  const size = isCore ? 1.2 : 0.4 + model.accuracy * 0.8;
  const color =
    model.status === "active" ? "#22c55e" :
    model.status === "training" ? "#f59e0b" : "#6b7280";

  useFrame(({ clock }) => {
    if (!meshRef.current) return;
    meshRef.current.rotation.y = clock.elapsedTime * 0.3;
    meshRef.current.rotation.x = Math.sin(clock.elapsedTime * 0.5) * 0.1;
  });

  return (
    <group position={position}>
      <mesh
        ref={meshRef}
        onClick={(e) => { e.stopPropagation(); setClicked(!clicked); }}
      >
        <icosahedronGeometry args={[size, 1]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={model.status === "active" ? 0.6 : 0.2}
          wireframe={!isCore}
          transparent
          opacity={0.9}
        />
      </mesh>

      {/* Always-visible label */}
      <Html distanceFactor={10} position={[0, -size - 0.5, 0]} style={{ pointerEvents: "none" }}>
        <div className="text-center whitespace-nowrap select-none">
          <div className="text-xs font-bold text-white/90 bg-black/50 rounded px-1.5 py-0.5 backdrop-blur-sm border border-white/10">
            {isCore ? "Goblin AI" : model.model_name}
            <span
              className="inline-block w-1.5 h-1.5 rounded-full ml-1 align-middle"
              style={{ backgroundColor: color }}
            />
          </div>
          {!isCore && (
            <div className="text-[10px] text-gray-400 mt-0.5">
              {(model.accuracy * 100).toFixed(0)}% acc
            </div>
          )}
        </div>
      </Html>

      {/* Expanded detail panel on click */}
      {clicked && (
        <Html distanceFactor={10} position={[size + 1.5, 0, 0]} style={{ pointerEvents: "auto" }}>
          <div className="bg-gray-900/95 border border-goblin-500/30 rounded-lg p-3 w-56 backdrop-blur text-white">
            <div className="flex justify-between items-center mb-2">
              <span className="font-bold text-sm">{isCore ? "Goblin AI Ensemble" : model.model_name}</span>
              <button onClick={() => setClicked(false)} className="text-gray-400 hover:text-white text-xs">X</button>
            </div>
            <div className="space-y-1.5 text-xs text-gray-300">
              <div className="flex justify-between">
                <span>Status</span>
                <span style={{ color }}>{model.status}</span>
              </div>
              <div className="flex justify-between">
                <span>Version</span>
                <span className="text-white">{model.version}</span>
              </div>
              <div>
                <div className="flex justify-between mb-0.5">
                  <span>Accuracy</span>
                  <span className="text-white">{(model.accuracy * 100).toFixed(1)}%</span>
                </div>
                <div className="w-full bg-gray-700 rounded-full h-1.5">
                  <div className="h-1.5 rounded-full" style={{ width: `${model.accuracy * 100}%`, backgroundColor: color }} />
                </div>
              </div>
              <div className="flex justify-between">
                <span>Last Retrain</span>
                <span className="text-white">{new Date(model.last_retrain).toLocaleDateString()}</span>
              </div>
            </div>
          </div>
        </Html>
      )}
    </group>
  );
}
