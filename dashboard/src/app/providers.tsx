"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { useRealtimeUpdates } from "@/hooks/useRealtimeUpdates";
import { useAlertEvaluator } from "@/hooks/useAlertEvaluator";

function RealtimeUpdater() {
  useRealtimeUpdates();
  return null;
}

function AlertEvaluator() {
  useAlertEvaluator();
  return null;
}

export default function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 2000,
            retry: 2,
            refetchOnWindowFocus: true,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      <RealtimeUpdater />
      <AlertEvaluator />
      {children}
    </QueryClientProvider>
  );
}
