"use client";

import { Loader2, WifiOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useGuest } from "@/hooks/useGuest";
import { useServerWaking } from "@/hooks/useServerStatus";

/** Shown when the backend is slow (free hosting waking up) or unreachable. */
export function ServerStatusBanner() {
  const waking = useServerWaking();
  const { error, loading, refresh } = useGuest();
  const offline = !!error && error.isNetworkError && !loading;

  if (!waking && !offline) return null;
  return (
    <div role="status" aria-live="polite" className="border-b border-border bg-card">
      <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2 text-sm sm:px-6">
        {offline ? (
          <>
            <WifiOff className="size-4 shrink-0 text-destructive" aria-hidden />
            <span className="flex-1 text-muted-foreground">Can&apos;t reach the server right now.</span>
            <Button size="sm" variant="outline" onClick={() => void refresh()}>
              Retry
            </Button>
          </>
        ) : (
          <>
            <Loader2 className="size-4 shrink-0 animate-spin text-brand" aria-hidden />
            <span className="text-muted-foreground">
              The server is waking up. The first request can take up to a minute, thanks for waiting.
            </span>
          </>
        )}
      </div>
    </div>
  );
}
