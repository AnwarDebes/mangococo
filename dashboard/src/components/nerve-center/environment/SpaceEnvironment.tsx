"use client";

import { Stars } from "@react-three/drei";

export default function SpaceEnvironment() {
  return (
    <>
      <Stars
        radius={100}
        depth={50}
        count={3000}
        factor={4}
        saturation={0}
        fade
      />
      <ambientLight intensity={0.15} />
      <directionalLight position={[10, 20, 10]} intensity={0.8} />
      <pointLight position={[0, 10, 0]} intensity={0.5} color="#22c55e" distance={30} />
      <pointLight position={[-20, 5, 0]} intensity={0.3} color="#3b82f6" distance={25} />
    </>
  );
}
