"use client";

import { useState, useRef, useCallback, useMemo } from "react";
import { cn } from "@/lib/utils";
import type { StrategyNode, StrategyConnection } from "@/types";

const PORT_SIZE = 8;
const NODE_W = 180;
const NODE_H = 72;

const TYPE_COLORS: Record<string, { border: string; bg: string; text: string }> = {
  trigger: { border: "border-l-blue-500", bg: "bg-blue-500/10", text: "text-blue-400" },
  condition: { border: "border-l-yellow-500", bg: "bg-yellow-500/10", text: "text-yellow-400" },
  action: { border: "border-l-green-500", bg: "bg-green-500/10", text: "text-green-400" },
};

interface CanvasProps {
  nodes: StrategyNode[];
  connections: StrategyConnection[];
  onNodesChange: (nodes: StrategyNode[]) => void;
  onConnectionsChange: (connections: StrategyConnection[]) => void;
  onNodeSelect: (nodeId: string | null) => void;
  selectedNodeId: string | null;
}

export default function StrategyCanvas({
  nodes,
  connections,
  onNodesChange,
  onConnectionsChange,
  onNodeSelect,
  selectedNodeId,
}: CanvasProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [dragNode, setDragNode] = useState<string | null>(null);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [connecting, setConnecting] = useState<{ fromId: string; mx: number; my: number } | null>(null);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const isPanning = useRef(false);
  const panStart = useRef({ x: 0, y: 0, px: 0, py: 0 });

  const handleMouseDown = useCallback((e: React.MouseEvent, nodeId: string) => {
    e.stopPropagation();
    const node = nodes.find((n) => n.id === nodeId);
    if (!node) return;
    setDragNode(nodeId);
    setDragOffset({ x: e.clientX / zoom - node.x - pan.x, y: e.clientY / zoom - node.y - pan.y });
    onNodeSelect(nodeId);
  }, [nodes, zoom, pan, onNodeSelect]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (dragNode) {
      const updated = nodes.map((n) =>
        n.id === dragNode
          ? { ...n, x: e.clientX / zoom - dragOffset.x - pan.x, y: e.clientY / zoom - dragOffset.y - pan.y }
          : n
      );
      onNodesChange(updated);
    }
    if (connecting) {
      setConnecting({ ...connecting, mx: e.clientX / zoom - pan.x, my: e.clientY / zoom - pan.y });
    }
    if (isPanning.current) {
      setPan({
        x: panStart.current.px + (e.clientX - panStart.current.x) / zoom,
        y: panStart.current.py + (e.clientY - panStart.current.y) / zoom,
      });
    }
  }, [dragNode, connecting, nodes, dragOffset, zoom, pan, onNodesChange]);

  const handleMouseUp = useCallback(() => {
    setDragNode(null);
    setConnecting(null);
    isPanning.current = false;
  }, []);

  const handlePortDown = useCallback((e: React.MouseEvent, nodeId: string) => {
    e.stopPropagation();
    const node = nodes.find((n) => n.id === nodeId);
    if (!node) return;
    setConnecting({
      fromId: nodeId,
      mx: node.x + NODE_W,
      my: node.y + NODE_H / 2,
    });
  }, [nodes]);

  const handleInputPortUp = useCallback((e: React.MouseEvent, nodeId: string) => {
    e.stopPropagation();
    if (connecting && connecting.fromId !== nodeId) {
      const exists = connections.some(
        (c) => c.from === connecting.fromId && c.to === nodeId
      );
      if (!exists) {
        onConnectionsChange([
          ...connections,
          { id: `${connecting.fromId}-${nodeId}`, from: connecting.fromId, to: nodeId },
        ]);
      }
    }
    setConnecting(null);
  }, [connecting, connections, onConnectionsChange]);

  const handleCanvasMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.target === svgRef.current) {
      onNodeSelect(null);
      isPanning.current = true;
      panStart.current = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y };
    }
  }, [onNodeSelect, pan]);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    const newZoom = Math.max(0.3, Math.min(2, zoom - e.deltaY * 0.001));
    setZoom(newZoom);
  }, [zoom]);

  // Render bezier curves for connections
  const connectionPaths = useMemo(() => {
    return connections.map((conn) => {
      const from = nodes.find((n) => n.id === conn.from);
      const to = nodes.find((n) => n.id === conn.to);
      if (!from || !to) return null;
      const x1 = from.x + NODE_W;
      const y1 = from.y + NODE_H / 2;
      const x2 = to.x;
      const y2 = to.y + NODE_H / 2;
      const cx = (x1 + x2) / 2;
      return { id: conn.id, d: `M ${x1} ${y1} C ${cx} ${y1}, ${cx} ${y2}, ${x2} ${y2}` };
    }).filter(Boolean) as { id: string; d: string }[];
  }, [connections, nodes]);

  return (
    <div className="relative flex-1 overflow-hidden rounded-lg border border-gray-800 bg-gray-950/80">
      {/* Dot grid background */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage: "radial-gradient(circle, #1f2937 1px, transparent 1px)",
          backgroundSize: `${20 * zoom}px ${20 * zoom}px`,
          backgroundPosition: `${pan.x * zoom}px ${pan.y * zoom}px`,
        }}
      />

      <svg
        ref={svgRef}
        className="w-full h-full cursor-grab active:cursor-grabbing"
        onMouseDown={handleCanvasMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onWheel={handleWheel}
      >
        <g transform={`scale(${zoom}) translate(${pan.x}, ${pan.y})`}>
          {/* Connection lines */}
          {connectionPaths.map((path) => (
            <path
              key={path.id}
              d={path.d}
              fill="none"
              stroke="#22c55e"
              strokeWidth={2}
              opacity={0.6}
            />
          ))}

          {/* Temp connection while dragging */}
          {connecting && (() => {
            const from = nodes.find((n) => n.id === connecting.fromId);
            if (!from) return null;
            const x1 = from.x + NODE_W;
            const y1 = from.y + NODE_H / 2;
            const cx = (x1 + connecting.mx) / 2;
            return (
              <path
                d={`M ${x1} ${y1} C ${cx} ${y1}, ${cx} ${connecting.my}, ${connecting.mx} ${connecting.my}`}
                fill="none"
                stroke="#22c55e"
                strokeWidth={2}
                strokeDasharray="4 4"
                opacity={0.4}
              />
            );
          })()}

          {/* Nodes */}
          {nodes.map((node) => {
            const colors = TYPE_COLORS[node.type] || TYPE_COLORS.trigger;
            const isSelected = selectedNodeId === node.id;
            return (
              <g key={node.id}>
                {/* Node body */}
                <foreignObject
                  x={node.x}
                  y={node.y}
                  width={NODE_W}
                  height={NODE_H}
                >
                  <div
                    className={cn(
                      "h-full w-full rounded-lg border-l-[3px] border border-gray-700 cursor-move select-none",
                      colors.border,
                      colors.bg,
                      isSelected && "ring-1 ring-goblin-500"
                    )}
                    onMouseDown={(e) => handleMouseDown(e as unknown as React.MouseEvent, node.id)}
                  >
                    <div className="px-3 py-2">
                      <p className={cn("text-[10px] font-medium uppercase tracking-wider", colors.text)}>
                        {node.type}
                      </p>
                      <p className="text-xs font-bold text-white mt-0.5 truncate">
                        {node.name}
                      </p>
                      <p className="text-[9px] text-gray-500 mt-0.5 truncate">
                        {node.category}
                      </p>
                    </div>
                  </div>
                </foreignObject>

                {/* Input port (left) */}
                {node.type !== "trigger" && (
                  <circle
                    cx={node.x}
                    cy={node.y + NODE_H / 2}
                    r={PORT_SIZE / 2}
                    fill="#374151"
                    stroke="#6b7280"
                    strokeWidth={1}
                    className="cursor-crosshair"
                    onMouseUp={(e) => handleInputPortUp(e, node.id)}
                  />
                )}

                {/* Output port (right) */}
                {node.type !== "action" && (
                  <circle
                    cx={node.x + NODE_W}
                    cy={node.y + NODE_H / 2}
                    r={PORT_SIZE / 2}
                    fill="#22c55e"
                    stroke="#16a34a"
                    strokeWidth={1}
                    className="cursor-crosshair"
                    onMouseDown={(e) => handlePortDown(e, node.id)}
                  />
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {/* Zoom controls */}
      <div className="absolute bottom-3 right-3 flex gap-1">
        <button
          onClick={() => setZoom(Math.min(2, zoom + 0.1))}
          className="h-7 w-7 rounded bg-gray-800 text-gray-400 hover:text-white text-sm border border-gray-700"
        >
          +
        </button>
        <button
          onClick={() => setZoom(Math.max(0.3, zoom - 0.1))}
          className="h-7 w-7 rounded bg-gray-800 text-gray-400 hover:text-white text-sm border border-gray-700"
        >
          −
        </button>
        <button
          onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}
          className="h-7 px-2 rounded bg-gray-800 text-gray-400 hover:text-white text-[10px] border border-gray-700"
        >
          Reset
        </button>
      </div>
    </div>
  );
}
