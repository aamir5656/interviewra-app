"use client";

import { motion } from "framer-motion";
import { useEffect } from "react";

import { ScoreRing } from "@/components/report/ScoreRing";
import { scoreTone } from "@/lib/report";
import type { Report } from "@/types";

/** Light confetti for a strong score. Skipped with reduced motion; the library loads only when needed. */
function useConfetti(score: number) {
  useEffect(() => {
    if (score < 80 || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let cancelled = false;
    void import("canvas-confetti").then(({ default: confetti }) => {
      if (cancelled) return;
      const opts = { particleCount: 45, spread: 70, startVelocity: 38, ticks: 140, disableForReducedMotion: true, zIndex: 30 };
      confetti({ ...opts, angle: 60, origin: { x: 0.1, y: 0.7 } });
      confetti({ ...opts, angle: 120, origin: { x: 0.9, y: 0.7 } });
    });
    return () => {
      cancelled = true;
    };
  }, [score]);
}

export function ScoreCard({ report, title }: { report: Report; title?: string }) {
  useConfetti(report.overall_score);
  const tone = scoreTone(report.has_critical ? Math.min(report.overall_score, 59) : report.overall_score);
  const label = report.verdict || tone.label;
  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="flex flex-col items-center gap-6 rounded-xl border border-border bg-card p-6 sm:flex-row sm:gap-8 sm:p-8 print:flex-row print:break-inside-avoid"
    >
      <ScoreRing score={report.overall_score} />
      <div className="min-w-0 text-center sm:text-left">
        {title && <p className="truncate text-sm text-muted-foreground print:whitespace-normal">{title}</p>}
        <h1 className="font-heading text-2xl font-bold sm:text-3xl">
          <span className={tone.text}>{label}</span>
        </h1>
        <p className="mt-3 leading-relaxed text-muted-foreground">{report.summary}</p>
      </div>
    </motion.section>
  );
}
