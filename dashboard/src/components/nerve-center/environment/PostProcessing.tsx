"use client";

import { EffectComposer, Bloom, Vignette } from "@react-three/postprocessing";

export default function PostProcessing() {
  return (
    <EffectComposer>
      <Bloom luminanceThreshold={0.6} luminanceSmoothing={0.9} intensity={0.8} />
      <Vignette darkness={0.5} offset={0.3} />
    </EffectComposer>
  );
}
