"use client";

import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import { Line } from "@react-three/drei";
import * as THREE from "three";
import { ZONES, ZONE_CONNECTIONS, getZoneById } from "../zones/ZoneConfig";

/** Animated dashed flow lines connecting zones — the kingdom's nervous system */
export default function DataFlowLines() {
  return (
    <group>
      {ZONE_CONNECTIONS.map((conn, i) => (
        <FlowLine key={i} fromZone={conn.from} toZone={conn.to} color={conn.color} index={i} />
      ))}
    </group>
  );
}

function FlowLine({
  fromZone,
  toZone,
  color,
  index,
}: {
  fromZone: string;
  toZone: string;
  color: string;
  index: number;
}) {
  const fromDef = getZoneById(fromZone as any);
  const toDef = getZoneById(toZone as any);
  if (!fromDef || !toDef) return null;

  const points = useMemo(() => {
    const start = new THREE.Vector3(...fromDef.position);
    const end = new THREE.Vector3(...toDef.position);
    start.y += 1.5;
    end.y += 1.5;
    const mid = new THREE.Vector3().addVectors(start, end).multiplyScalar(0.5);
    mid.y += 3 + index * 0.3;
    const curve = new THREE.QuadraticBezierCurve3(start, mid, end);
    return curve.getPoints(30).map((p): [number, number, number] => [p.x, p.y, p.z]);
  }, [fromDef, toDef, index]);

  return (
    <Line
      points={points}
      color={color}
      lineWidth={1}
      transparent
      opacity={0.2}
      dashed
      dashSize={0.5}
      gapSize={0.3}
    />
  );
}
