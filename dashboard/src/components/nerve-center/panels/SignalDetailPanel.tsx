"use client";

import { Html } from "@react-three/drei";
import type { Signal } from "@/types";

interface SignalDetailPanelProps {
  signal: Signal;
  position: [number, number, number];
  onClose: () => void;
}

export default function SignalDetailPanel({ signal, position, onClose }: SignalDetailPanelProps) {
  return (
    <group position={position}>
      <Html distanceFactor={15} style={{ pointerEvents: "auto" }}>
        <div className="bg-gray-900/95 border border-goblin-500/30 rounded-lg p-3 w-52 backdrop-blur text-white">
          <div className="flex justify-between items-center mb-2">
            <span className="font-bold text-sm">Signal</span>
            <button onClick={onClose} className="text-gray-400 hover:text-white text-xs">X</button>
          </div>
          <div className="space-y-1 text-xs text-gray-300">
            <div className="flex justify-between">
              <span>Action</span>
              <span className={
                signal.action === "BUY" ? "text-green-400" :
                signal.action === "SELL" ? "text-red-400" : "text-yellow-400"
              }>
                {signal.action}
              </span>
            </div>
            <div className="flex justify-between">
              <span>Confidence</span>
              <span>{(signal.confidence * 100).toFixed(0)}%</span>
            </div>
            <div className="flex justify-between">
              <span>Symbol</span>
              <span>{signal.symbol}</span>
            </div>
            <div className="flex justify-between">
              <span>Price</span>
              <span>${signal.price.toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span>Time</span>
              <span>{new Date(signal.timestamp).toLocaleTimeString()}</span>
            </div>
          </div>
        </div>
      </Html>
    </group>
  );
}
