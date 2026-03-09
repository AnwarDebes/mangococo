"use client";

import dynamic from "next/dynamic";

const NerveCenterScene = dynamic(
  () => import("@/components/nerve-center/NerveCenterScene"),
  { ssr: false }
);
const NerveCenterHUD = dynamic(
  () => import("@/components/nerve-center/NerveCenterHUD"),
  { ssr: false }
);

export default function NerveCenterPage() {
  return (
    <div className="relative h-[calc(100vh-4rem)] w-full overflow-hidden rounded-xl border border-goblin-500/20">
      <NerveCenterScene />
      <NerveCenterHUD />
    </div>
  );
}
