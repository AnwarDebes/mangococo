"use client";

import { Grid } from "@react-three/drei";

export default function GridFloor() {
  return (
    <Grid
      position={[0, -5, 0]}
      cellSize={2}
      cellThickness={0.5}
      cellColor="#1a3d15"
      sectionSize={10}
      sectionColor="#22c55e"
      fadeDistance={50}
      fadeStrength={1}
      infiniteGrid
    />
  );
}
