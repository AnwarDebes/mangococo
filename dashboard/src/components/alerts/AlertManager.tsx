"use client";

import { useState } from "react";
import { Bell, Plus, Trash2, RotateCcw } from "lucide-react";
import { useAlertStore, type AlertCondition } from "@/stores/alertStore";
import { cn } from "@/lib/utils";

const CONDITION_TYPES = [
  { value: "price_above", label: "Price Above" },
  { value: "price_below", label: "Price Below" },
  { value: "fear_greed_above", label: "Fear & Greed Above" },
  { value: "fear_greed_below", label: "Fear & Greed Below" },
  { value: "funding_rate_extreme", label: "Funding Rate Extreme" },
];

const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"];

function describeCondition(c: AlertCondition): string {
  switch (c.type) {
    case "price_above": return `${c.symbol} > $${c.value.toLocaleString()}`;
    case "price_below": return `${c.symbol} < $${c.value.toLocaleString()}`;
    case "fear_greed_above": return `Fear & Greed > ${c.value}`;
    case "fear_greed_below": return `Fear & Greed < ${c.value}`;
    case "funding_rate_extreme": return `${c.symbol} funding > ${c.threshold}%`;
    case "volume_spike": return `${c.symbol} volume ${c.multiplier}x`;
    case "correlation_break": return `${c.pair[0]}/${c.pair[1]} corr < ${c.threshold}`;
    default: return "Unknown";
  }
}

export default function AlertManager() {
  const { alerts, addAlert, removeAlert, toggleAlert, resetAlert } = useAlertStore();
  const [isOpen, setIsOpen] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [condType, setCondType] = useState("price_above");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [value, setValue] = useState("");

  const handleAdd = () => {
    if (!name.trim() || !value.trim()) return;
    const numVal = parseFloat(value);
    if (isNaN(numVal)) return;

    let condition: AlertCondition;
    switch (condType) {
      case "price_above":
        condition = { type: "price_above", symbol, value: numVal };
        break;
      case "price_below":
        condition = { type: "price_below", symbol, value: numVal };
        break;
      case "fear_greed_above":
        condition = { type: "fear_greed_above", value: numVal };
        break;
      case "fear_greed_below":
        condition = { type: "fear_greed_below", value: numVal };
        break;
      case "funding_rate_extreme":
        condition = { type: "funding_rate_extreme", symbol, threshold: numVal };
        break;
      default:
        return;
    }

    addAlert(name.trim(), condition);
    setName("");
    setValue("");
    setShowForm(false);
  };

  const triggeredCount = alerts.filter((a) => a.triggered).length;
  const needsSymbol = ["price_above", "price_below", "funding_rate_extreme"].includes(condType);

  return (
    <>
      {/* Bell trigger button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="relative p-2 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
      >
        <Bell size={18} />
        {triggeredCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 h-4 w-4 rounded-full bg-gold-500 text-[9px] font-bold flex items-center justify-center text-black">
            {triggeredCount}
          </span>
        )}
      </button>

      {/* Alert panel */}
      {isOpen && (
        <div className="absolute right-0 top-full mt-2 w-80 bg-gray-900/95 backdrop-blur-xl border border-gray-800 rounded-xl shadow-2xl z-50 max-h-[500px] overflow-y-auto">
          <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <h3 className="text-sm font-bold text-white">Smart Alerts</h3>
            <button
              onClick={() => setShowForm(!showForm)}
              className="text-goblin-500 hover:text-goblin-400 transition-colors"
            >
              <Plus size={16} />
            </button>
          </div>

          {/* Add form */}
          {showForm && (
            <div className="px-4 py-3 border-b border-gray-800 space-y-2">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Alert name"
                className="w-full bg-gray-800 rounded-lg px-3 py-1.5 text-xs text-white placeholder-gray-500 outline-none border border-gray-700 focus:border-goblin-500/50"
              />
              <select
                value={condType}
                onChange={(e) => setCondType(e.target.value)}
                className="w-full bg-gray-800 rounded-lg px-3 py-1.5 text-xs text-white outline-none border border-gray-700"
              >
                {CONDITION_TYPES.map((ct) => (
                  <option key={ct.value} value={ct.value}>{ct.label}</option>
                ))}
              </select>
              {needsSymbol && (
                <select
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                  className="w-full bg-gray-800 rounded-lg px-3 py-1.5 text-xs text-white outline-none border border-gray-700"
                >
                  {SYMBOLS.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              )}
              <input
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="Threshold value"
                type="number"
                className="w-full bg-gray-800 rounded-lg px-3 py-1.5 text-xs text-white placeholder-gray-500 outline-none border border-gray-700 focus:border-goblin-500/50"
              />
              <button onClick={handleAdd} className="btn-goblin text-xs w-full py-1.5">Add Alert</button>
            </div>
          )}

          {/* Alert list */}
          <div className="px-2 py-2 space-y-1">
            {alerts.length === 0 && (
              <p className="text-center text-xs text-gray-500 py-4">No alerts configured</p>
            )}
            {alerts.map((alert) => (
              <div
                key={alert.id}
                className={cn(
                  "px-3 py-2 rounded-lg text-xs transition-colors",
                  alert.triggered ? "bg-gold-500/10 border border-gold-500/30" : "bg-gray-800/50"
                )}
              >
                <div className="flex items-center justify-between">
                  <span className={cn("font-medium", alert.triggered ? "text-gold-400" : "text-white")}>
                    {alert.name}
                  </span>
                  <div className="flex items-center gap-1">
                    {alert.triggered && (
                      <button onClick={() => resetAlert(alert.id)} className="text-gray-500 hover:text-white p-0.5">
                        <RotateCcw size={11} />
                      </button>
                    )}
                    <button
                      onClick={() => toggleAlert(alert.id)}
                      className={cn(
                        "h-4 w-7 rounded-full transition-colors relative",
                        alert.enabled ? "bg-goblin-500" : "bg-gray-600"
                      )}
                    >
                      <div className={cn(
                        "absolute top-0.5 h-3 w-3 rounded-full bg-white transition-transform",
                        alert.enabled ? "left-3.5" : "left-0.5"
                      )} />
                    </button>
                    <button onClick={() => removeAlert(alert.id)} className="text-gray-500 hover:text-red-400 p-0.5">
                      <Trash2 size={11} />
                    </button>
                  </div>
                </div>
                <p className="text-gray-500 mt-0.5">{describeCondition(alert.condition)}</p>
                {alert.triggered && (
                  <p className="text-gold-500 text-[10px] mt-0.5">Triggered</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
