"use client";

import { useState, useMemo, useRef } from "react";

interface CorrelationHeatmapProps {
  symbols: string[];
  matrix: number[][];
}

interface HoverState {
  row: number;
  col: number;
  value: number;
  x: number;
  y: number;
}

function getCorrelationColor(value: number): string {
  const clamped = Math.max(-1, Math.min(1, value));
  if (clamped > 0) {
    const intensity = clamped;
    const r = Math.round(239 * intensity + 255 * (1 - intensity));
    const g = Math.round(68 * intensity + 255 * (1 - intensity));
    const b = Math.round(68 * intensity + 255 * (1 - intensity));
    return `rgb(${r},${g},${b})`;
  } else {
    const intensity = Math.abs(clamped);
    const r = Math.round(59 * intensity + 255 * (1 - intensity));
    const g = Math.round(130 * intensity + 255 * (1 - intensity));
    const b = Math.round(246 * intensity + 255 * (1 - intensity));
    return `rgb(${r},${g},${b})`;
  }
}
export default function CorrelationHeatmap({ symbols, matrix }: CorrelationHeatmapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<HoverState | null>(null);
  const n = symbols.length;

  const layout = useMemo(() => {
    const labelPadding = 60;
    const maxWidth = 600;
    const cellSize = Math.max(24, Math.min(48, Math.floor((maxWidth - labelPadding) / n)));
    const gridSize = cellSize * n;
    const totalWidth = labelPadding + gridSize;
    const totalHeight = labelPadding + gridSize;
    return { labelPadding, cellSize, gridSize, totalWidth, totalHeight };
  }, [n]);

  if (n === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-gray-500">
        No correlation data available
      </div>
    );
  }
  const { labelPadding, cellSize, gridSize, totalWidth, totalHeight } = layout;
  const showText = cellSize >= 32;

  return (
    <div className="relative" ref={containerRef}>
      <svg width={totalWidth} height={totalHeight} className="block">
        {/* Y-axis labels */}
        {symbols.map((sym, i) => (
          <text
            key={`y-${i}`}
            x={labelPadding - 6}
            y={labelPadding + i * cellSize + cellSize / 2 + 4}
            fill="#d1d5db"
            fontSize="11"
            textAnchor="end"
            fontFamily="monospace"
          >
            {sym}
          </text>
        ))}

        {/* X-axis labels (rotated) */}
        {symbols.map((sym, i) => (
          <text
            key={`x-${i}`}
            x={0}
            y={0}
            fill="#d1d5db"
            fontSize="11"
            textAnchor="start"
            fontFamily="monospace"
            transform={`translate(${labelPadding + i * cellSize + cellSize / 2}, ${labelPadding - 6}) rotate(-45)`}
          >
            {sym}
          </text>
        ))}
        {/* Cells */}
        {matrix.map((row, ri) =>
          row.map((value, ci) => {
            const isHighlighted = hover !== null && (hover.row === ri || hover.col === ci);
            const isHovered = hover !== null && hover.row === ri && hover.col === ci;
            return (
              <g key={`${ri}-${ci}`}>
                <rect
                  x={labelPadding + ci * cellSize}
                  y={labelPadding + ri * cellSize}
                  width={cellSize - 1}
                  height={cellSize - 1}
                  fill={getCorrelationColor(value)}
                  opacity={hover === null || isHighlighted ? 1 : 0.3}
                  stroke={isHovered ? "#ffc107" : "none"}
                  strokeWidth={isHovered ? 2 : 0}
                  className="cursor-pointer transition-opacity duration-150"
                  onMouseEnter={(e) => {
                    const rect = e.currentTarget.getBoundingClientRect();
                    setHover({
                      row: ri,
                      col: ci,
                      value,
                      x: rect.left + rect.width / 2,
                      y: rect.top,
                    });
                  }}
                  onMouseLeave={() => setHover(null)}
                />
                {showText && (
                  <text
                    x={labelPadding + ci * cellSize + (cellSize - 1) / 2}
                    y={labelPadding + ri * cellSize + (cellSize - 1) / 2 + 4}
                    fill={Math.abs(value) > 0.5 ? "#ffffff" : "#1f2937"}
                    fontSize="9"
                    textAnchor="middle"
                    className="pointer-events-none"
                  >
                    {value.toFixed(2)}
                  </text>
                )}
              </g>
            );
          })
        )}
      </svg>
      {hover && (
        <div
          className="pointer-events-none fixed z-50 rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 shadow-lg"
          style={{ left: hover.x, top: hover.y - 8, transform: "translate(-50%, -100%)" }}
        >
          <p className="text-xs text-gray-400">
            {symbols[hover.row]} / {symbols[hover.col]}
          </p>
          <p className="text-sm font-bold text-white">
            {hover.value.toFixed(3)}
          </p>
        </div>
      )}

      {/* Color legend */}
      <div className="mt-3 flex items-center justify-center gap-2 text-xs text-gray-500">
        <span>-1.0</span>
        <div className="flex h-3">
          {Array.from({ length: 20 }).map((_, i) => (
            <div
              key={i}
              className="h-3 w-3"
              style={{ backgroundColor: getCorrelationColor((i / 19) * 2 - 1) }}
            />
          ))}
        </div>
        <span>+1.0</span>
      </div>
    </div>
  );
}