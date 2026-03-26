"use client";

import { useState, useCallback } from "react";
import {
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Download,
} from "lucide-react";
import {
  formatCurrency,
  formatPrice,
  formatPercent,
  getPnlColor,
  cn,
} from "@/lib/utils";
import { useTrades } from "@/hooks/usePortfolio";
import { getTrades } from "@/lib/api";

const PAGE_SIZE_OPTIONS = [10, 20, 50] as const;

const CSV_HEADERS = [
  "closed_at",
  "created_at",
  "symbol",
  "side",
  "entry_price",
  "exit_price",
  "amount",
  "realized_pnl",
  "pnl_pct",
  "hold_time_seconds",
  "exit_reason",
  "strategy",
] as const;

function escapeCsv(value: string | number): string {
  const str = String(value);
  if (str.includes(",") || str.includes('"') || str.includes("\n")) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

export default function TradeHistory() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(20);
  const [sortAsc, setSortAsc] = useState(false);
  const [exporting, setExporting] = useState(false);

  const sort = sortAsc ? "asc" : "desc";
  const { data, isLoading, isFetching } = useTrades(page, pageSize, sort);

  const trades = data?.trades ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const handlePageSize = (size: number) => {
    setPageSize(size);
    setPage(1);
  };

  const handleSort = () => {
    setSortAsc(!sortAsc);
    setPage(1);
  };

  const handleExport = useCallback(async () => {
    setExporting(true);
    try {
      // First fetch to get total count, then fetch all
      const { total: totalCount } = await getTrades(1, 0, "desc");
      const { trades: allTrades } = await getTrades(totalCount || 100000, 0, "desc");
      const rows = allTrades.map((t) =>
        CSV_HEADERS.map((h) => escapeCsv(t[h])).join(",")
      );
      const csv = [CSV_HEADERS.join(","), ...rows].join("\n");

      const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `goblin_trades_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  }, []);

  if (isLoading) {
    return (
      <div className="card animate-pulse space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-8 rounded bg-gray-700" />
        ))}
      </div>
    );
  }

  return (
    <div className="card overflow-hidden p-0">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-800 px-5 py-3">
        <div className="flex items-center gap-3">
          <h3 className="font-semibold text-white">Recent Trades</h3>
          {total > 0 && (
            <span className="text-xs text-gray-500">
              {total} total
            </span>
          )}
          {isFetching && !isLoading && (
            <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
          )}
          <button
            onClick={handleSort}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-white transition-colors"
          >
            <ArrowUpDown size={14} />
            {sortAsc ? "Oldest" : "Newest"}
          </button>
        </div>
        <button
          onClick={handleExport}
          disabled={exporting || total === 0}
          className="flex items-center gap-1.5 rounded-md border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 hover:border-green-500/50 hover:text-white disabled:opacity-40 disabled:hover:border-gray-700 disabled:hover:text-gray-300 transition-colors"
          title="Download all trades as CSV"
        >
          <Download size={14} className={exporting ? "animate-bounce" : ""} />
          {exporting ? "Exporting..." : "Export CSV"}
        </button>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-left text-xs text-gray-500">
              <th className="px-5 py-2">Time</th>
              <th className="px-3 py-2">Symbol</th>
              <th className="px-3 py-2">Side</th>
              <th className="px-3 py-2 text-right">Entry</th>
              <th className="px-3 py-2 text-right">Exit</th>
              <th className="px-3 py-2 text-right">PnL</th>
              <th className="px-3 py-2 text-right">PnL%</th>
              <th className="px-3 py-2">Reason</th>
              <th className="px-5 py-2">Strategy</th>
            </tr>
          </thead>
          <tbody>
            {trades.length === 0 ? (
              <tr>
                <td
                  colSpan={9}
                  className="px-5 py-8 text-center text-gray-500"
                >
                  No trades yet
                </td>
              </tr>
            ) : (
              trades.map((trade, i) => (
                <tr
                  key={`${trade.symbol}-${trade.closed_at}-${i}`}
                  className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors"
                >
                  <td className="whitespace-nowrap px-5 py-2.5 text-xs text-gray-400">
                    {new Date(trade.closed_at).toLocaleString("en-GB", {
                      day: "2-digit",
                      month: "2-digit",
                      year: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                      hour12: false,
                    })}
                  </td>
                  <td className="px-3 py-2.5 font-medium text-white">
                    {trade.symbol}
                  </td>
                  <td className="px-3 py-2.5">
                    <span
                      className={cn(
                        "badge",
                        trade.side === "long" ? "badge-buy" : "badge-sell"
                      )}
                    >
                      {trade.side.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-gray-300">
                    ${formatPrice(trade.entry_price)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-gray-300">
                    ${formatPrice(trade.exit_price)}
                  </td>
                  <td
                    className={cn(
                      "px-3 py-2.5 text-right font-mono font-medium",
                      getPnlColor(trade.realized_pnl)
                    )}
                  >
                    {formatCurrency(trade.realized_pnl)}
                  </td>
                  <td
                    className={cn(
                      "px-3 py-2.5 text-right font-mono",
                      getPnlColor(trade.pnl_pct)
                    )}
                  >
                    {formatPercent(trade.pnl_pct,4)}
                  </td>
                  <td className="px-3 py-2.5 text-xs text-gray-400">
                    {trade.exit_reason}
                  </td>
                  <td className="px-5 py-2.5 text-xs text-gray-400">
                    {trade.strategy}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination footer */}
      {total > 0 && (
        <div className="flex items-center justify-between border-t border-gray-800 px-5 py-2.5">
          {/* Page size selector */}
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <span>Rows</span>
            <select
              value={pageSize}
              onChange={(e) => handlePageSize(Number(e.target.value))}
              className="rounded border border-gray-700 bg-gray-800 px-2 py-1 text-xs text-gray-300 outline-none focus:border-green-500"
            >
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </div>

          {/* Page info + navigation */}
          <div className="flex items-center gap-1">
            <span className="mr-3 text-xs text-gray-400">
              {(page - 1) * pageSize + 1}–
              {Math.min(page * pageSize, total)} of {total}
            </span>

            <button
              onClick={() => setPage(1)}
              disabled={page <= 1}
              className="rounded p-1 text-gray-400 hover:bg-gray-700 hover:text-white disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-gray-400 transition-colors"
              title="First page"
            >
              <ChevronsLeft size={16} />
            </button>
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="rounded p-1 text-gray-400 hover:bg-gray-700 hover:text-white disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-gray-400 transition-colors"
              title="Previous page"
            >
              <ChevronLeft size={16} />
            </button>
            <span className="mx-2 text-xs text-gray-300">
              {page} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="rounded p-1 text-gray-400 hover:bg-gray-700 hover:text-white disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-gray-400 transition-colors"
              title="Next page"
            >
              <ChevronRight size={16} />
            </button>
            <button
              onClick={() => setPage(totalPages)}
              disabled={page >= totalPages}
              className="rounded p-1 text-gray-400 hover:bg-gray-700 hover:text-white disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-gray-400 transition-colors"
              title="Last page"
            >
              <ChevronsRight size={16} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
