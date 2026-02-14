"use client";

import { useMemo } from "react";

interface Headline {
  title: string;
  sentiment: "positive" | "negative" | "neutral";
  source: string;
  timestamp: string;
}

interface NewsTickerProps {
  headlines: Array<Headline>;
}

const SENTIMENT_DOTS: Record<Headline["sentiment"], string> = {
  positive: "\u{1F7E2}",
  negative: "\u{1F534}",
  neutral: "\u{26AA}",
};

const SENTIMENT_COLORS: Record<Headline["sentiment"], string> = {
  positive: "text-profit",
  negative: "text-loss",
  neutral: "text-gray-400",
};
function HeadlineItem({ headline }: { headline: Headline }) {
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap px-6">
      <span className="text-sm">{SENTIMENT_DOTS[headline.sentiment]}</span>
      <span className={`text-sm font-medium ${SENTIMENT_COLORS[headline.sentiment]}`}>
        {headline.title}
      </span>
      <span className="rounded bg-gray-800 px-1.5 py-0.5 text-[10px] text-gray-500">
        {headline.source}
      </span>
    </span>
  );
}

export default function NewsTicker({ headlines }: NewsTickerProps) {
  const items = useMemo(() => {
    if (!headlines || headlines.length === 0) return [];
    return headlines;
  }, [headlines]);

  if (items.length === 0) {
    return null;
  }

  // Calculate animation duration based on content length (approx 50px/s)
  const estimatedWidth = items.length * 350;
  const duration = estimatedWidth / 50;
  return (
    <div className="fixed bottom-0 left-0 right-0 z-40 h-10 overflow-hidden border-t border-gray-800 bg-gray-950/90 backdrop-blur-sm">
      <style jsx>{`
        @keyframes ticker-scroll {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
        .ticker-track {
          animation: ticker-scroll ${duration}s linear infinite;
        }
        .ticker-track:hover {
          animation-play-state: paused;
        }
      `}</style>
      <div className="flex h-full items-center">
        <div className="ticker-track flex items-center">
          {/* Original content */}
          {items.map((headline, i) => (
            <HeadlineItem key={`a-${i}`} headline={headline} />
          ))}
          {/* Duplicated for seamless loop */}
          {items.map((headline, i) => (
            <HeadlineItem key={`b-${i}`} headline={headline} />
          ))}
        </div>
      </div>
    </div>
  );
}