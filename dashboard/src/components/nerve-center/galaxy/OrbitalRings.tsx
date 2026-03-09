"use client";

import { useMemo } from "react";
import { Line } from "@react-three/drei";
import { circlePoints } from "@/lib/nerve-center-utils";

export default function OrbitalRings() {
  const rings = useMemo(
    () => [8, 16, 24].map((r) => circlePoints(r, 64, 0)),
    []
  );

  return (
    <>
      {rings.map((points, i) => (
        <Line
          key={i}
          points={points}
          color="#22c55e"
          lineWidth={0.5}
          opacity={0.1}
          transparent
          dashed
          dashSize={0.5}
          gapSize={0.5}
        />
      ))}
    </>
  );
}
