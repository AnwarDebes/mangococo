import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

function toNumber(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return 0;
}

export function formatCurrency(value: unknown): string {
  const num = toNumber(value);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(num);
}

export function formatPrice(value: unknown): string {
  const num = toNumber(value);
  const abs = Math.abs(num);

  let decimals = 2;
  if (abs < 1000) decimals = 4;
  if (abs < 10) decimals = 6;
  if (abs < 1) decimals = 8;

  return num.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatPercent(value: unknown, fractionDigits = 2): string {
  const raw = toNumber(value);
  // Heuristic: values in [-1,1] are treated as fractional returns.
  const pct = Math.abs(raw) <= 1 ? raw * 100 : raw;
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(fractionDigits)}%`;
}

export function getPnlColor(value: unknown): string {
  const num = toNumber(value);
  if (num > 0) return "text-profit";
  if (num < 0) return "text-loss";
  return "text-neutral";
}

export function getTimeSince(timestamp: string | null | undefined): string {
  if (!timestamp) return "n/a";

  const ts = new Date(timestamp);
  if (Number.isNaN(ts.getTime())) return "n/a";

  const diffMs = Date.now() - ts.getTime();
  if (diffMs < 0) return "just now";

  const sec = Math.floor(diffMs / 1000);
  if (sec < 10) return "just now";
  if (sec < 60) return `${sec}s ago`;

  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;

  const hours = Math.floor(min / 60);
  if (hours < 24) return `${hours}h ago`;

  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;

  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;

  const years = Math.floor(months / 12);
  return `${years}y ago`;
}

export function formatLargeNumber(n: number): string {
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  return `$${n.toLocaleString()}`;
}

/**
 * Compute max drawdown from a chronologically sorted list of trades.
 * Walks cumulative equity (startingCapital + running sum of realized_pnl),
 * tracks peak, and returns the deepest (equity - peak) / peak * 100.
 */
export function computeMaxDrawdown(
  trades: Array<{ realized_pnl: number; closed_at: string }>,
  startingCapital: number,
): number {
  if (!trades || trades.length === 0) return 0;

  const sorted = [...trades].sort(
    (a, b) => new Date(a.closed_at).getTime() - new Date(b.closed_at).getTime(),
  );

  let equity = startingCapital;
  let peak = equity;
  let maxDd = 0;

  for (const t of sorted) {
    equity += t.realized_pnl;
    if (equity > peak) peak = equity;
    if (peak > 0) {
      const dd = ((equity - peak) / peak) * 100;
      if (dd < maxDd) maxDd = dd;
    }
  }

  return maxDd;
}
