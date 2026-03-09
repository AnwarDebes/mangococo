"use client";

import { useNerveCenterStore } from "../NerveCenterStore";
import type { KingdomEvent } from "../NerveCenterStore";

function formatTimeAgo(ts: number): string {
  const diff = Math.floor((Date.now() - ts) / 1000);
  if (diff < 5) return "now";
  if (diff < 60) return `${diff}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  return `${Math.floor(diff / 3600)}h`;
}

export default function EventFeed() {
  const eventFeed = useNerveCenterStore((s) => s.eventFeed);
  const showEventFeed = useNerveCenterStore((s) => s.showEventFeed);
  const toggleEventFeed = useNerveCenterStore((s) => s.toggleEventFeed);

  return (
    <div className="absolute top-16 left-3 pointer-events-auto w-64">
      <div className="bg-gray-950/90 backdrop-blur-md border border-amber-700/30 rounded-xl overflow-hidden shadow-2xl">
        <button
          onClick={toggleEventFeed}
          className="w-full flex items-center justify-between px-3 py-2 bg-gradient-to-r from-amber-900/40 to-transparent"
        >
          <div className="flex items-center gap-2">
            <span className="text-amber-400 text-sm">📜</span>
            <span className="text-amber-300 text-[10px] font-bold uppercase tracking-wider">Kingdom Log</span>
            {eventFeed.length > 0 && (
              <span className="bg-amber-500/20 text-amber-400 text-[9px] font-bold px-1.5 rounded">
                {eventFeed.length}
              </span>
            )}
          </div>
          <span className="text-gray-500 text-xs">{showEventFeed ? "▲" : "▼"}</span>
        </button>

        {showEventFeed && (
          <div className="max-h-[35vh] overflow-y-auto px-2 py-1.5 space-y-1">
            {eventFeed.length === 0 ? (
              <div className="text-center py-4 text-gray-600 text-[10px] italic">
                The kingdom is quiet...
              </div>
            ) : (
              eventFeed.map((event) => (
                <EventRow key={event.id} event={event} />
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function EventRow({ event }: { event: KingdomEvent }) {
  return (
    <div className="flex items-start gap-2 bg-gray-900/50 rounded-lg px-2 py-1.5 border border-gray-800/50">
      <span className="text-sm shrink-0 mt-0.5">{event.icon}</span>
      <div className="flex-1 min-w-0">
        <p className="text-[10px] leading-tight" style={{ color: event.color }}>
          {event.message}
        </p>
        <span className="text-[8px] text-gray-600">{formatTimeAgo(event.timestamp)}</span>
      </div>
    </div>
  );
}
