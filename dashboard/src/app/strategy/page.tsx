"use client";

import { useState, useCallback } from "react";
import { AlertCircle, Check, Save, Upload } from "lucide-react";
import StrategyCanvas from "@/components/strategy/StrategyCanvas";
import NodePalette from "@/components/strategy/NodePalette";
import NodeConfig from "@/components/strategy/NodeConfig";
import StrategyTemplates from "@/components/strategy/StrategyTemplates";
import { cn } from "@/lib/utils";
import type { StrategyNode, StrategyConnection } from "@/types";

const STORAGE_KEY = "goblin-strategies";

export default function StrategyPage() {
  const [nodes, setNodes] = useState<StrategyNode[]>([]);
  const [connections, setConnections] = useState<StrategyConnection[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(true);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [validated, setValidated] = useState(false);

  const selectedNode = nodes.find((n) => n.id === selectedNodeId) ?? null;

  const handleAddNode = useCallback(
    (partial: Omit<StrategyNode, "id" | "x" | "y">) => {
      const id = `node_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
      const x = 200 + Math.random() * 200;
      const y = 100 + Math.random() * 200;
      setNodes((prev) => [...prev, { ...partial, id, x, y }]);
    },
    []
  );

  const handleUpdateNode = useCallback((updated: StrategyNode) => {
    setNodes((prev) => prev.map((n) => (n.id === updated.id ? updated : n)));
  }, []);

  const handleDeleteNode = useCallback(
    (nodeId: string) => {
      setNodes((prev) => prev.filter((n) => n.id !== nodeId));
      setConnections((prev) =>
        prev.filter((c) => c.from !== nodeId && c.to !== nodeId)
      );
      if (selectedNodeId === nodeId) setSelectedNodeId(null);
    },
    [selectedNodeId]
  );

  const handleLoadTemplate = useCallback(
    (templateNodes: StrategyNode[], templateConns: StrategyConnection[]) => {
      setNodes(templateNodes);
      setConnections(templateConns);
      setSelectedNodeId(null);
      setValidationErrors([]);
      setValidated(false);
    },
    []
  );

  const handleValidate = useCallback(() => {
    const errors: string[] = [];

    // Check for disconnected nodes
    const connectedIds = new Set<string>();
    connections.forEach((c) => {
      connectedIds.add(c.from);
      connectedIds.add(c.to);
    });
    for (const node of nodes) {
      if (!connectedIds.has(node.id) && nodes.length > 1) {
        errors.push(`Node "${node.name}" is disconnected`);
      }
    }

    // Check for triggers (must have at least one)
    if (!nodes.some((n) => n.type === "trigger")) {
      errors.push("Strategy needs at least one trigger node");
    }

    // Check for actions (must have at least one)
    if (!nodes.some((n) => n.type === "action")) {
      errors.push("Strategy needs at least one action node");
    }

    // Check for cycles (simple DFS)
    const adj: Record<string, string[]> = {};
    for (const c of connections) {
      if (!adj[c.from]) adj[c.from] = [];
      adj[c.from].push(c.to);
    }
    const visited = new Set<string>();
    const stack = new Set<string>();
    const hasCycle = (nodeId: string): boolean => {
      if (stack.has(nodeId)) return true;
      if (visited.has(nodeId)) return false;
      visited.add(nodeId);
      stack.add(nodeId);
      for (const next of adj[nodeId] || []) {
        if (hasCycle(next)) return true;
      }
      stack.delete(nodeId);
      return false;
    };
    for (const n of nodes) {
      if (hasCycle(n.id)) {
        errors.push("Strategy graph contains a cycle");
        break;
      }
    }

    setValidationErrors(errors);
    setValidated(true);
  }, [nodes, connections]);

  const handleSave = useCallback(() => {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]") as Array<{
      name: string;
      nodes: StrategyNode[];
      connections: StrategyConnection[];
    }>;
    const name = `Strategy ${saved.length + 1}`;
    saved.push({ name, nodes, connections });
    localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));
  }, [nodes, connections]);

  const handleLoad = useCallback(() => {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]") as Array<{
      name: string;
      nodes: StrategyNode[];
      connections: StrategyConnection[];
    }>;
    if (saved.length > 0) {
      const latest = saved[saved.length - 1];
      setNodes(latest.nodes);
      setConnections(latest.connections);
      setSelectedNodeId(null);
    }
  }, []);

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] gap-2">
      {/* Header */}
      <div className="flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-white">Strategy Builder</h1>
          <p className="text-xs text-gray-500">Visual node editor for trading strategies</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleValidate} className="btn-goblin px-3 py-1.5 text-xs flex items-center gap-1.5">
            <Check size={14} />
            Validate
          </button>
          <button onClick={handleSave} className="px-3 py-1.5 text-xs rounded-lg bg-gray-800 text-gray-300 border border-gray-700 hover:text-white flex items-center gap-1.5">
            <Save size={14} />
            Save
          </button>
          <button onClick={handleLoad} className="px-3 py-1.5 text-xs rounded-lg bg-gray-800 text-gray-300 border border-gray-700 hover:text-white flex items-center gap-1.5">
            <Upload size={14} />
            Load
          </button>
        </div>
      </div>

      {/* Validation feedback */}
      {validated && (
        <div className={cn(
          "shrink-0 px-3 py-2 rounded-lg text-xs flex items-center gap-2",
          validationErrors.length === 0
            ? "bg-green-500/10 text-green-400 border border-green-500/20"
            : "bg-red-500/10 text-red-400 border border-red-500/20"
        )}>
          <AlertCircle size={14} />
          {validationErrors.length === 0
            ? "Strategy is valid!"
            : validationErrors.join(". ")}
        </div>
      )}

      {/* Main layout: palette | canvas | config */}
      <div className="flex-1 min-h-0 flex gap-2">
        {/* Left: Palette */}
        <div className={cn(
          "shrink-0 overflow-y-auto transition-all",
          paletteOpen ? "w-48" : "w-0"
        )}>
          {paletteOpen && (
            <div className="card h-full overflow-y-auto p-3 space-y-4">
              <NodePalette onAddNode={handleAddNode} />
              <div className="border-t border-gray-800 pt-3">
                <StrategyTemplates onLoad={handleLoadTemplate} />
              </div>
            </div>
          )}
        </div>

        {/* Toggle button */}
        <button
          onClick={() => setPaletteOpen(!paletteOpen)}
          className="shrink-0 self-start mt-2 px-1 py-4 rounded bg-gray-800 text-gray-400 hover:text-white border border-gray-700 text-[10px]"
        >
          {paletteOpen ? "◄" : "►"}
        </button>

        {/* Center: Canvas */}
        <StrategyCanvas
          nodes={nodes}
          connections={connections}
          onNodesChange={setNodes}
          onConnectionsChange={setConnections}
          onNodeSelect={setSelectedNodeId}
          selectedNodeId={selectedNodeId}
        />

        {/* Right: Node config */}
        {selectedNode && (
          <div className="shrink-0 w-52 card overflow-y-auto p-3">
            <NodeConfig
              node={selectedNode}
              onUpdate={handleUpdateNode}
              onDelete={handleDeleteNode}
            />
          </div>
        )}
      </div>

      <p className="text-[10px] text-gray-600 shrink-0">
        Drag nodes from palette. Connect output ports (green) to input ports (gray). Pan with background drag, zoom with scroll.
      </p>
    </div>
  );
}
