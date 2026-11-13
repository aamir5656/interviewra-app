"use client";

import { motion, useReducedMotion } from "framer-motion";
import { Sparkles } from "lucide-react";

import { DURATION, EASE } from "@/components/landing/motion";

const BUBBLES = [
  { who: "Alex (AI interviewer)", text: "A query on a big table got slow. How do you find the cause, and when would you add an index?", me: false },
  { who: "You", text: "I'd check the query plan with EXPLAIN first, then index the columns used in the filter.", me: true },
];

export function ChatPreview() {
  const reduce = useReducedMotion();
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: DURATION.slow, ease: EASE, delay: reduce ? 0 : 0.5 }}
      className="mx-auto w-full max-w-xl rounded-2xl border border-border bg-card/90 p-4 shadow-xl backdrop-blur sm:p-5"
      aria-label="Example of an interview chat"
    >
      <div className="space-y-3">
        {BUBBLES.map((b, i) => (
          <motion.div
            key={b.who}
            initial={reduce ? false : { opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: DURATION.base, ease: EASE, delay: reduce ? 0 : 0.8 + i * 0.35 }}
            className={b.me ? "ml-8 rounded-xl rounded-br-sm bg-primary/15 p-3" : "mr-8 rounded-xl rounded-bl-sm bg-muted p-3"}
          >
            <p className="mb-1 text-xs font-medium text-muted-foreground">{b.who}</p>
            <p className="text-sm leading-relaxed">{b.text}</p>
          </motion.div>
        ))}
      </div>
      <motion.div
        initial={reduce ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: DURATION.base, delay: reduce ? 0 : 1.6 }}
        className="mt-4 flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm"
      >
        <Sparkles className="size-4 text-brand" aria-hidden />
        <span className="text-muted-foreground">Report preview:</span>
        <span className="font-semibold text-brand">Depth 72</span>
        <span className="text-muted-foreground">· Mention the write cost of indexes</span>
      </motion.div>
    </motion.div>
  );
}
