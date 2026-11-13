"use client";

import { motion, useReducedMotion } from "framer-motion";

import { CATEGORY_KEYS, CATEGORY_LABELS, scoreTone } from "@/lib/report";
import type { CategoryScores } from "@/types";

/** One bar per category, filling in sequence. */
export function CategoryBars({ scores }: { scores: CategoryScores }) {
  const reduce = useReducedMotion();
  return (
    <section className="rounded-xl border border-border bg-card p-6 print:break-inside-avoid">
      <h2 className="font-heading text-lg font-semibold">Skill breakdown</h2>
      <ul className="mt-4 space-y-4">
        {CATEGORY_KEYS.map((key, i) => {
          const value = scores[key];
          return (
            <li key={key}>
              <div className="mb-1.5 flex justify-between text-sm">
                <span>{CATEGORY_LABELS[key]}</span>
                <span className="font-medium tabular-nums">{value}</span>
              </div>
              <div className="h-2.5 overflow-hidden rounded-full bg-muted" role="presentation">
                <motion.div
                  className={`h-full rounded-full ${scoreTone(value).bar}`}
                  initial={{ width: reduce ? `${value}%` : 0 }}
                  animate={{ width: `${value}%` }}
                  transition={{ duration: 0.8, delay: 0.3 + i * 0.15, ease: "easeOut" }}
                />
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
