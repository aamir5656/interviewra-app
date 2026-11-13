"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Sparkles } from "lucide-react";

/** Small pill showing what the interviewer is doing ("Choosing the next topic"). */
export function ToolHint({ label }: { label: string | null }) {
  const reduce = useReducedMotion();
  return (
    <div className="flex min-h-8 justify-start pl-9" aria-live="polite">
      <AnimatePresence mode="wait">
        {label && (
          <motion.span
            key={label}
            initial={reduce ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: -4 }}
            transition={{ duration: 0.2 }}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-xs text-muted-foreground"
          >
            <Sparkles className="size-3.5 animate-pulse text-brand" aria-hidden />
            {label}…
          </motion.span>
        )}
      </AnimatePresence>
    </div>
  );
}
