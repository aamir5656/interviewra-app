"use client";

import { Timer, X } from "lucide-react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

interface Props {
  /** A new key (e.g. the question number) restarts the countdown. */
  resetKey: string | number;
  /** Counts down only while true (paused while Alex is writing). */
  running: boolean;
  seconds: number;
  onHide: () => void;
}

const WARN_AT = 30;

/** Optional per-question countdown. Turns amber near the end; never blocks answering. */
export function QuestionTimer({ resetKey, running, seconds, onHide }: Props) {
  const [remaining, setRemaining] = useState(seconds);
  const [key, setKey] = useState(resetKey);
  if (key !== resetKey) {
    setKey(resetKey);
    setRemaining(seconds);
  }

  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => setRemaining((r) => Math.max(0, r - 1)), 1000);
    return () => window.clearInterval(id);
  }, [running, resetKey]);

  const warn = remaining <= WARN_AT;
  const over = remaining === 0;
  const mm = Math.floor(remaining / 60);
  const ss = String(remaining % 60).padStart(2, "0");
  return (
    <span
      role="timer"
      aria-label={over ? "Suggested time for this question is up" : `${mm} minutes ${ss} seconds left for this question`}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs tabular-nums transition-colors",
        warn ? "border-amber-500/50 bg-amber-500/10 text-amber-500" : "border-border text-muted-foreground",
      )}
    >
      <Timer className="size-3.5" aria-hidden />
      {over ? "Time is up, wrap up" : `${mm}:${ss}`}
      <button type="button" onClick={onHide} aria-label="Hide timer" className="-mr-1 rounded-full p-0.5 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
        <X className="size-3" />
      </button>
    </span>
  );
}
