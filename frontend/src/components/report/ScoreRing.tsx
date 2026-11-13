"use client";

import { animate, useMotionValue, useReducedMotion, useTransform, motion } from "framer-motion";
import { useEffect, useState } from "react";

import { scoreTone } from "@/lib/report";

const SIZE = 176;
const STROKE = 12;
const R = (SIZE - STROKE) / 2;
const C = 2 * Math.PI * R;

/** Circular score gauge: the ring fills and the number counts up from 0. Shows the final value at once with reduced motion. */
export function ScoreRing({ score }: { score: number }) {
  const reduce = useReducedMotion();
  const progress = useMotionValue(reduce ? score : 0);
  const offset = useTransform(progress, (v) => C * (1 - v / 100));
  const [shown, setShown] = useState(reduce ? score : 0);

  useEffect(() => {
    if (reduce) return;
    const controls = animate(progress, score, { duration: 1.4, ease: [0.22, 1, 0.36, 1], onUpdate: (v) => setShown(Math.round(v)) });
    return () => controls.stop();
  }, [score, reduce, progress]);

  const value = reduce ? score : shown;
  return (
    <div className="relative size-44 shrink-0" role="img" aria-label={`Overall score ${score} out of 100`}>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="size-full -rotate-90">
        <circle cx={SIZE / 2} cy={SIZE / 2} r={R} fill="none" strokeWidth={STROKE} className="stroke-border" />
        <motion.circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={R}
          fill="none"
          strokeWidth={STROKE}
          strokeLinecap="round"
          strokeDasharray={C}
          style={{ strokeDashoffset: offset }}
          className={scoreTone(score).stroke}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-heading text-5xl leading-none font-bold tabular-nums">{value}</span>
        <span className="mt-1 text-xs text-muted-foreground">out of 100</span>
      </div>
    </div>
  );
}
