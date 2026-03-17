import type { Metadata } from "next";
import "./globals.css";
import Providers from "./providers";
import Sidebar from "@/components/layout/Sidebar";
import Header from "@/components/layout/Header";
import GoblinBackground from "@/components/effects/GoblinBackground";
import NotificationProvider from "@/components/notifications/NotificationProvider";
import CommandPalette from "@/components/CommandPalette";
import SafeguardsStrip from "@/components/panels/SafeguardsStrip";
import CursorTrail from "@/components/effects/CursorTrail";
import CelebrationEffects from "@/components/effects/CelebrationEffects";
import DynamicFavicon from "@/components/effects/DynamicFavicon";
import KeyboardShortcuts from "@/components/modals/KeyboardShortcuts";
import GoblinChat from "@/components/GoblinChat";
import ErrorBoundary from "@/components/ErrorBoundary";
import dynamic from "next/dynamic";

const FamiliarOverlay = dynamic(() => import("@/components/familiar/FamiliarOverlay"), {
  ssr: false,
});

export const metadata: Metadata = {
  title: "Goblin - AI Trading Dashboard",
  description: "Real-time AI-powered crypto trading monitoring dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body>
        <Providers>
          <NotificationProvider />
          <CommandPalette />
          <CursorTrail />
          <CelebrationEffects />
          <DynamicFavicon />
          <KeyboardShortcuts />
          <GoblinChat />
          <FamiliarOverlay />
          <GoblinBackground />
          <div className="relative z-10 flex h-[100dvh] overflow-hidden">
            <Sidebar />
            <div className="flex min-w-0 flex-1 flex-col lg:ml-64">
              <Header />
              <SafeguardsStrip />
              <main className="flex-1 overflow-x-hidden overflow-y-auto p-2 sm:p-4 lg:p-6">
                <ErrorBoundary>
                  <div className="animate-fade-in">{children}</div>
                </ErrorBoundary>
              </main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
