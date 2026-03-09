"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import SignalBeam from "./SignalBeam";
import type { Signal } from "@/types";
import { signalColor } from "@/lib/nerve-center-utils";

interface BeamData {
  id: string;
  from: [number, number, number];
  to: [number, number, number];
  color: string;
}

// Zone positions for beam targets
const ORACLE_POS: [number, number, number] = [12, 2, 16];
const TREASURY_POS: [number, number, number] = [0, 2, 0];
const WAR_ROOM_POS: [number, number, number] = [0, 1, -20];

interface ActivityBeamManagerProps {
  signals: Signal[];
}

export default function ActivityBeamManager({ signals }: ActivityBeamManagerProps) {
  const [activeBeams, setActiveBeams] = useState<BeamData[]>([]);
  const prevSignalIds = useRef<Set<string>>(new Set());
  const initRef = useRef(false);

  useEffect(() => {
    // Skip first render to avoid beaming all existing signals
    if (!initRef.current) {
      initRef.current = true;
      prevSignalIds.current = new Set(signals.map((s) => s.signal_id));
      return;
    }

    const currentIds = new Set(signals.map((s) => s.signal_id));
    const newSignals = signals.filter((s) => !prevSignalIds.current.has(s.signal_id));
    prevSignalIds.current = currentIds;

    if (newSignals.length > 0) {
      const newBeams: BeamData[] = newSignals.slice(0, 3).map((s) => ({
        id: `beam-${s.signal_id}-${Date.now()}`,
        from: ORACLE_POS,
        to: s.action === "BUY" ? WAR_ROOM_POS : TREASURY_POS,
        color: signalColor(s.action),
      }));

      setActiveBeams((prev) => [...prev, ...newBeams].slice(-5));
    }
  }, [signals]);

  const removeBeam = useCallback((id: string) => {
    setActiveBeams((prev) => prev.filter((b) => b.id !== id));
  }, []);

  return (
    <group>
      {activeBeams.map((beam) => (
        <SignalBeam
          key={beam.id}
          from={beam.from}
          to={beam.to}
          color={beam.color}
          onComplete={() => removeBeam(beam.id)}
        />
      ))}
    </group>
  );
}
