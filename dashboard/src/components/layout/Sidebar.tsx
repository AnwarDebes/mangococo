"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  CandlestickChart,
  BarChart3,
  Brain,
  Server,
  Coins,
  ScrollText,
  FlaskConical,
  Radar,
  Workflow,
  History,
  Menu,
  X,
} from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/war-room", label: "War Room", icon: Radar },
  { href: "/trading", label: "Trading", icon: CandlestickChart },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/backtesting", label: "Backtesting", icon: FlaskConical },
  { href: "/strategy", label: "Strategy", icon: Workflow },
  { href: "/replay", label: "Replay", icon: History },
  { href: "/sentiment", label: "Sentiment", icon: Brain },
  { href: "/goblin-coin", label: "GBLN Coin", icon: Coins },
  { href: "/system", label: "System", icon: Server },
  { href: "/logs", label: "Logs", icon: ScrollText },
];

function GoblinLogo({ size = 36 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 256 256"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id="sidebarBg" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style={{ stopColor: "#2d5a27" }} />
          <stop offset="100%" style={{ stopColor: "#1a3d15" }} />
        </linearGradient>
        <linearGradient id="sidebarSkin" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style={{ stopColor: "#7cb342" }} />
          <stop offset="100%" style={{ stopColor: "#558b2f" }} />
        </linearGradient>
        <linearGradient id="sidebarEar" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style={{ stopColor: "#8bc34a" }} />
          <stop offset="100%" style={{ stopColor: "#689f38" }} />
        </linearGradient>
        <linearGradient id="sidebarGold" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style={{ stopColor: "#fbbf24" }} />
          <stop offset="100%" style={{ stopColor: "#d97706" }} />
        </linearGradient>
      </defs>
      <circle cx="128" cy="128" r="124" fill="url(#sidebarGold)" />
      <circle cx="128" cy="128" r="116" fill="url(#sidebarBg)" />
      <ellipse cx="50" cy="100" rx="25" ry="38" fill="url(#sidebarEar)" transform="rotate(-30 50 100)" />
      <ellipse cx="206" cy="100" rx="25" ry="38" fill="url(#sidebarEar)" transform="rotate(30 206 100)" />
      <ellipse cx="128" cy="140" rx="68" ry="63" fill="url(#sidebarSkin)" />
      <ellipse cx="102" cy="132" rx="18" ry="22" fill="#fff" />
      <ellipse cx="105" cy="134" rx="10" ry="12" fill="#2d2d2d" />
      <circle cx="109" cy="128" r="4" fill="#fff" />
      <ellipse cx="154" cy="132" rx="18" ry="22" fill="#fff" />
      <ellipse cx="157" cy="134" rx="10" ry="12" fill="#2d2d2d" />
      <circle cx="161" cy="128" r="4" fill="#fff" />
      <ellipse cx="128" cy="156" rx="10" ry="6" fill="#558b2f" />
      <circle cx="123" cy="155" r="2" fill="#2d2d2d" />
      <circle cx="133" cy="155" r="2" fill="#2d2d2d" />
      <path d="M100 175 Q128 200 156 175" stroke="#2d2d2d" strokeWidth="3" fill="none" strokeLinecap="round" />
      <circle cx="102" cy="78" r="10" fill="url(#sidebarSkin)" />
      <circle cx="154" cy="78" r="10" fill="url(#sidebarSkin)" />
    </svg>
  );
}

export default function Sidebar() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <>
      {/* Mobile toggle */}
      <button
        onClick={() => setMobileOpen(!mobileOpen)}
        className="fixed left-4 top-4 z-50 rounded-lg bg-gray-800 p-2 lg:hidden border border-goblin-500/20"
      >
        {mobileOpen ? <X size={20} /> : <Menu size={20} />}
      </button>

      {/* Overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          "fixed left-0 top-0 z-40 flex h-full w-64 flex-col border-r border-goblin-800/50 bg-gray-950 transition-transform lg:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        {/* Subtle side glow */}
        <div className="absolute right-0 top-0 bottom-0 w-px bg-gradient-to-b from-transparent via-goblin-500/30 to-transparent" />

        {/* Logo */}
        <div className="flex h-16 items-center gap-3 border-b border-gray-800/50 px-5 gradient-border">
          <div className="relative">
            <GoblinLogo size={38} />
            <div className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-goblin-500 glow-green-sm" />
          </div>
          <div className="flex flex-col">
            <span className="text-lg font-bold text-goblin-gradient">Goblin</span>
            <span className="text-[10px] text-gold-500 font-medium -mt-0.5 tracking-wider">AI TRADING</span>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 space-y-1 px-3 py-4">
          {navItems.map((item) => {
            const isActive =
              pathname === item.href ||
              (item.href !== "/" && pathname.startsWith(item.href));
            const isGbln = item.href === "/goblin-coin";
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMobileOpen(false)}
                className={cn(
                  "relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200 sidebar-nav-item",
                  isActive
                    ? "bg-goblin-500/10 text-goblin-400 border border-goblin-500/20 glow-green-sm"
                    : "text-gray-400 hover:bg-gray-800/50 hover:text-white border border-transparent",
                  isGbln && !isActive && "text-gold-500/80 hover:text-gold-400"
                )}
              >
                <item.icon size={20} className={isGbln && !isActive ? "text-gold-500/80" : ""} />
                {item.label}
                {isGbln && (
                  <span className="ml-auto text-[9px] font-bold bg-gold-500/20 text-gold-400 px-1.5 py-0.5 rounded-full">
                    NEW
                  </span>
                )}
              </Link>
            );
          })}
        </nav>

        {/* Footer with Goblin Mascot */}
        <div className="border-t border-gray-800/50 px-6 py-4">
          <div className="flex items-center gap-3">
            {/* Animated mini goblin mascot */}
            <svg width="32" height="32" viewBox="0 0 256 256" className="shrink-0 goblin-mascot">
              <defs>
                <linearGradient id="mascotSkin" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" style={{ stopColor: "#7cb342" }} />
                  <stop offset="100%" style={{ stopColor: "#558b2f" }} />
                </linearGradient>
              </defs>
              <ellipse cx="50" cy="100" rx="22" ry="35" fill="#8bc34a" transform="rotate(-30 50 100)" />
              <ellipse cx="206" cy="100" rx="22" ry="35" fill="#8bc34a" transform="rotate(30 206 100)" />
              <ellipse cx="128" cy="140" rx="65" ry="60" fill="url(#mascotSkin)" />
              {/* Eyes with blink animation */}
              <g className="goblin-eyes">
                <ellipse cx="102" cy="132" rx="16" ry="20" fill="#fff" />
                <ellipse cx="105" cy="134" rx="9" ry="11" fill="#2d2d2d" />
                <circle cx="109" cy="128" r="3.5" fill="#fff" />
                <ellipse cx="154" cy="132" rx="16" ry="20" fill="#fff" />
                <ellipse cx="157" cy="134" rx="9" ry="11" fill="#2d2d2d" />
                <circle cx="161" cy="128" r="3.5" fill="#fff" />
              </g>
              <ellipse cx="128" cy="156" rx="8" ry="5" fill="#558b2f" />
              <path d="M105 172 Q128 190 151 172" stroke="#2d2d2d" strokeWidth="3" fill="none" strokeLinecap="round" />
            </svg>
            <div>
              <div className="flex items-center gap-2">
                <div className="h-1.5 w-1.5 rounded-full bg-goblin-500 animate-pulse" />
                <p className="text-xs text-gray-500">Goblin v2.0</p>
              </div>
              <p className="text-xs text-gray-600 mt-0.5">AI Trading Platform</p>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
