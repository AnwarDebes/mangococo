"use client";

import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[error.tsx] Page error:", error);
  }, [error]);

  return (
    <div className="flex flex-col items-center justify-center min-h-[60dvh] gap-6 animate-fade-in">
      <div className="flex h-20 w-20 items-center justify-center rounded-full bg-red-500/10 border border-red-500/20">
        <svg
          width="40"
          height="40"
          viewBox="0 0 256 256"
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            <linearGradient id="errSkin" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" style={{ stopColor: "#ef4444" }} />
              <stop offset="100%" style={{ stopColor: "#b91c1c" }} />
            </linearGradient>
          </defs>
          <ellipse cx="128" cy="140" rx="65" ry="60" fill="url(#errSkin)" />
          <ellipse cx="102" cy="130" rx="16" ry="20" fill="#fff" />
          <ellipse cx="105" cy="132" rx="9" ry="11" fill="#2d2d2d" />
          <ellipse cx="154" cy="130" rx="16" ry="20" fill="#fff" />
          <ellipse cx="157" cy="132" rx="9" ry="11" fill="#2d2d2d" />
          <path
            d="M105 180 Q128 165 151 180"
            stroke="#2d2d2d"
            strokeWidth="3"
            fill="none"
            strokeLinecap="round"
          />
        </svg>
      </div>

      <div className="text-center max-w-md px-4">
        <h2 className="text-xl font-bold text-white mb-2">
          Something went wrong
        </h2>
        <p className="text-sm text-gray-400 mb-2">
          This page encountered an unexpected error. The rest of the dashboard
          is still operational.
        </p>
        {error.message && (
          <p className="text-xs font-mono text-red-400/70 bg-red-500/5 rounded-lg px-3 py-2 mb-4 break-all">
            {error.message}
          </p>
        )}
        <button
          onClick={reset}
          className="btn-goblin text-sm px-6 py-2.5"
        >
          Try Again
        </button>
      </div>
    </div>
  );
}
