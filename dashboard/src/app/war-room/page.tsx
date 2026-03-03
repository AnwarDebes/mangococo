"use client";

import ProbabilityCone from "@/components/war-room/ProbabilityCone";
import NeuralPulse from "@/components/war-room/NeuralPulse";
import SignalQueue from "@/components/war-room/SignalQueue";
import FactorHeatmap from "@/components/war-room/FactorHeatmap";
import DecisionStrip from "@/components/war-room/DecisionStrip";

export default function WarRoomPage() {
  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] gap-2">
      {/* Header */}
      <div className="flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-white">AI War Room</h1>
          <p className="text-xs text-gray-500">Real-time prediction theater</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-goblin-500 animate-pulse" />
          <span className="text-xs text-gray-400">Live</span>
        </div>
      </div>

      {/* Main grid: 3 columns on desktop, stacked on mobile */}
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[1fr_280px_200px] gap-2">
        {/* Left column: Probability Cone + Factor Heatmap */}
        <div className="flex flex-col gap-2 min-h-0">
          <div className="card flex-[3] min-h-[200px] overflow-hidden">
            <ProbabilityCone />
          </div>
          <div className="card flex-[2] min-h-[120px] overflow-hidden">
            <FactorHeatmap />
          </div>
        </div>

        {/* Middle column: Neural Pulse */}
        <div className="card min-h-[200px] lg:min-h-0 overflow-hidden">
          <NeuralPulse />
        </div>

        {/* Right column: Signal Queue */}
        <div className="card min-h-[200px] lg:min-h-0 overflow-hidden">
          <SignalQueue />
        </div>
      </div>

      {/* Bottom strip: Decision Timeline */}
      <div className="card shrink-0 h-[80px] sm:h-[90px] overflow-hidden">
        <DecisionStrip />
      </div>
    </div>
  );
}
