"use client";

import { useMemo } from "react";
import { Html } from "@react-three/drei";
import NeuronNode from "./NeuronNode";
import Synapse from "./Synapse";
import type { ModelStatus, FactorRow } from "@/types";

interface AIBrainNetworkProps {
  models: ModelStatus[];
  factors: FactorRow[];
}

const Y_OFFSET = 10;

export default function AIBrainNetwork({ models, factors }: AIBrainNetworkProps) {
  const layout = useMemo(() => {
    const coreModel: ModelStatus = {
      model_name: "Goblin AI",
      version: "ensemble",
      accuracy: 0.85,
      last_retrain: new Date().toISOString(),
      status: "active",
    };

    const modelPositions: { model: ModelStatus; pos: [number, number, number] }[] = models.map((m, i) => {
      const angle = (i / Math.max(models.length, 1)) * Math.PI * 2;
      const r = 5;
      return {
        model: m,
        pos: [Math.cos(angle) * r, Y_OFFSET + Math.sin(i * 1.3) * 1.5, Math.sin(angle) * r],
      };
    });

    // Factor nodes — top 8 factors from the first factorRow
    const topFactors: { name: string; direction: string; pos: [number, number, number] }[] = [];
    if (factors.length > 0) {
      const factorEntries = Object.entries(factors[0].factors).slice(0, 8);
      factorEntries.forEach(([name, data], i) => {
        const angle = (i / factorEntries.length) * Math.PI * 2 + 0.3;
        const r = 8;
        topFactors.push({
          name,
          direction: data.direction,
          pos: [Math.cos(angle) * r, Y_OFFSET + 3 + Math.sin(i * 0.8) * 1, Math.sin(angle) * r],
        });
      });
    }

    return { coreModel, modelPositions, topFactors };
  }, [models, factors]);

  return (
    <group position={[0, 0, 0]}>
      {/* Core neuron */}
      <NeuronNode model={layout.coreModel} position={[0, Y_OFFSET, 0]} isCore />

      {/* Model neurons + synapses to core */}
      {layout.modelPositions.map(({ model, pos }) => (
        <group key={model.model_name}>
          <NeuronNode model={model} position={pos} />
          <Synapse
            start={[0, Y_OFFSET, 0]}
            end={pos}
            active={model.status === "active"}
            color={
              model.status === "active" ? "#22c55e" :
              model.status === "training" ? "#f59e0b" : "#6b7280"
            }
            speed={model.accuracy}
          />
        </group>
      ))}

      {/* Factor nodes with labels + synapses to nearest model */}
      {layout.topFactors.map((f, i) => {
        const nearestModel = layout.modelPositions[i % Math.max(layout.modelPositions.length, 1)];
        const dirColor = f.direction === "bullish" ? "#22c55e" : f.direction === "bearish" ? "#ef4444" : "#8b5cf6";
        return (
          <group key={f.name}>
            <mesh position={f.pos}>
              <sphereGeometry args={[0.2, 12, 12]} />
              <meshStandardMaterial color={dirColor} emissive={dirColor} emissiveIntensity={0.5} />
            </mesh>
            <Html
              position={[f.pos[0], f.pos[1] - 0.5, f.pos[2]]}
              distanceFactor={10}
              style={{ pointerEvents: "none" }}
            >
              <div className="text-center whitespace-nowrap select-none">
                <div className="text-[10px] text-white/80 bg-black/50 rounded px-1 py-0.5 backdrop-blur-sm border border-white/10">
                  {f.name.replace(/_/g, " ")}
                  <span className="ml-1" style={{ color: dirColor }}>
                    {f.direction === "bullish" ? "▲" : f.direction === "bearish" ? "▼" : "●"}
                  </span>
                </div>
              </div>
            </Html>
            {nearestModel && (
              <Synapse start={nearestModel.pos} end={f.pos} active color={dirColor} speed={0.3} />
            )}
          </group>
        );
      })}
    </group>
  );
}
