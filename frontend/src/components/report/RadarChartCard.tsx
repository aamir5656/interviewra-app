"use client";

import { PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer } from "recharts";

import { CATEGORY_KEYS, CATEGORY_LABELS } from "@/lib/report";
import type { CategoryScores } from "@/types";

/** Radar of the four category scores (animated by Recharts; animation is off for print and reduced motion). */
export function RadarChartCard({ scores, title = "Skill shape" }: { scores: CategoryScores; title?: string }) {
  const data = CATEGORY_KEYS.map((key) => ({ category: CATEGORY_LABELS[key], score: scores[key] }));
  const reduce = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  return (
    <section className="rounded-xl border border-border bg-card p-6 print:break-inside-avoid">
      <h2 className="font-heading text-lg font-semibold">{title}</h2>
      <div className="mt-2 h-64 w-full" role="img" aria-label={data.map((d) => `${d.category} ${d.score}`).join(", ")}>
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart data={data} outerRadius="62%" margin={{ top: 12, right: 64, bottom: 12, left: 64 }}>
            <PolarGrid stroke="var(--border)" />
            <PolarAngleAxis dataKey="category" tick={{ fill: "var(--muted)", fontSize: 12 }} />
            <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
            <Radar
              dataKey="score"
              stroke="var(--accent)"
              fill="var(--accent)"
              fillOpacity={0.25}
              strokeWidth={2}
              isAnimationActive={!reduce}
              animationDuration={900}
            />
          </RadarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
