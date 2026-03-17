"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { useNotificationStore } from "@/stores/notificationStore";
import { API_BASE } from "@/lib/api";
import ToastContainer from "./Toast";

function playSound(type: "click" | "profit" | "loss") {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    gain.gain.value = 0.1;

    if (type === "click") {
      osc.frequency.value = 800;
      osc.start();
      osc.stop(ctx.currentTime + 0.05);
    } else if (type === "profit") {
      osc.frequency.value = 800;
      osc.start();
      osc.frequency.setValueAtTime(1200, ctx.currentTime + 0.1);
      osc.stop(ctx.currentTime + 0.2);
    } else {
      osc.frequency.value = 600;
      osc.start();
      osc.frequency.setValueAtTime(400, ctx.currentTime + 0.1);
      osc.stop(ctx.currentTime + 0.2);
    }
  } catch {}
}

export default function NotificationProvider() {
  const { addNotification, soundEnabled, notifications } = useNotificationStore();
  const [toasts, setToasts] = useState<typeof notifications>([]);
  const eventSourceRef = useRef<EventSource | null>(null);
  const lastPrices = useRef<Record<string, { price: number; time: number }>>({});
  const connectedRef = useRef(false);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // Sync new notifications to toast queue
  useEffect(() => {
    if (notifications.length > 0) {
      const latest = notifications[0];
      setToasts((prev) => {
        if (prev.find((t) => t.id === latest.id)) return prev;
        return [latest, ...prev].slice(0, 4);
      });
    }
  }, [notifications]);

  // Real SSE connection — no mock notifications
  useEffect(() => {
    let retryTimeout: ReturnType<typeof setTimeout>;
    let retryCount = 0;
    const maxRetries = 15;

    function connect() {
      try {
        if (eventSourceRef.current) {
          eventSourceRef.current.close();
        }

        const es = new EventSource(`${API_BASE}/api/stream`);
        eventSourceRef.current = es;

        es.onopen = () => {
          connectedRef.current = true;
          retryCount = 0;
          addNotification({
            type: "system",
            message: "Connected to live event stream",
            color: "green",
          });
        };

        es.addEventListener("trade_executed", (e) => {
          try {
            const data = JSON.parse(e.data);
            const isBuy = data.action === "BUY" || data.side === "long";
            const pnl = data.realized_pnl || 0;
            const pnlPct = data.pnl_pct || 0;
            const msg = isBuy
              ? `Bought ${data.amount} ${data.symbol} at $${Number(data.price).toLocaleString()}`
              : `Sold ${data.amount} ${data.symbol} at $${Number(data.price).toLocaleString()}${pnl ? ` (${pnl > 0 ? "+" : ""}$${pnl.toFixed(2)})` : ""}`;
            addNotification({ type: "trade", message: msg, color: isBuy ? "green" : "red", pnlPercent: Math.abs(pnlPct) });
            if (soundEnabled) playSound(pnl > 0 ? "profit" : pnl < 0 ? "loss" : "click");
          } catch {}
        });

        es.addEventListener("position_update", (e) => {
          try {
            const data = JSON.parse(e.data);
            const isOpen = data.action === "open";
            addNotification({
              type: "position",
              message: isOpen
                ? `New position opened: ${data.symbol} ${(data.side || "LONG").toUpperCase()}`
                : `Position closed: ${data.symbol} (${data.pnl_pct ? (data.pnl_pct > 0 ? "+" : "") + data.pnl_pct.toFixed(1) + "%" : ""})`,
              color: isOpen ? "green" : (data.pnl_pct || 0) >= 0 ? "green" : "red",
              pnlPercent: Math.abs(data.pnl_pct || 0),
            });
          } catch {}
        });

        es.addEventListener("price_update", (e) => {
          try {
            const data = JSON.parse(e.data);
            const symbol = data.symbol || "";
            const price = Number(data.price);
            const now = Date.now();
            const prev = lastPrices.current[symbol];

            if (prev && now - prev.time < 60000) {
              const change = ((price - prev.price) / prev.price) * 100;
              if (Math.abs(change) > 2) {
                addNotification({
                  type: "price",
                  message: `${symbol} ${change > 0 ? "surged" : "dropped"} ${change > 0 ? "+" : ""}${change.toFixed(1)}% in the last minute`,
                  color: "gold",
                });
              }
            }
            lastPrices.current[symbol] = { price, time: now };
          } catch {}
        });

        es.addEventListener("sentiment_update", (e) => {
          try {
            const data = JSON.parse(e.data);
            if (data.fear_greed_index !== undefined) {
              const fg = Number(data.fear_greed_index);
              if (fg < 25 || fg > 75) {
                addNotification({
                  type: "sentiment",
                  message: `Market sentiment shifted to ${fg < 25 ? `Extreme Fear (${fg})` : `Extreme Greed (${fg})`}`,
                  color: "blue",
                });
              }
            }
          } catch {}
        });

        es.onerror = () => {
          es.close();
          connectedRef.current = false;

          if (retryCount < maxRetries) {
            const delay = Math.min(1000 * Math.pow(2, retryCount), 30000);
            retryCount++;
            retryTimeout = setTimeout(connect, delay);
          }
        };
      } catch {
        if (retryCount < maxRetries) {
          const delay = Math.min(1000 * Math.pow(2, retryCount), 30000);
          retryCount++;
          retryTimeout = setTimeout(connect, delay);
        }
      }
    }

    connect();

    return () => {
      clearTimeout(retryTimeout);
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [addNotification, soundEnabled]);

  return <ToastContainer toasts={toasts} onDismiss={dismissToast} />;
}
