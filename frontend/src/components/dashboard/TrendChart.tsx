"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { TrendPoint } from "@/types";

const short = (iso: string) => new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });

/** Score over time (oldest first). */
export function TrendChart({ points }: { points: TrendPoint[] }) {
  const data = points.map((p, i) => ({ n: i + 1, label: short(p.date), score: p.score }));
  const reduce = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  return (
    <section className="rounded-xl border border-border bg-card p-6">
      <h2 className="font-heading text-lg font-semibold">Score trend</h2>
      <div className="mt-4 h-64 w-full" role="img" aria-label={`Scores over time: ${data.map((d) => d.score).join(", ")}`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="n" tickFormatter={(n: number) => `#${n}`} tick={{ fill: "var(--muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
            <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={{ fill: "var(--muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
            <Tooltip
              cursor={{ stroke: "var(--border)" }}
              contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text)" }}
              labelFormatter={(_, payload) => payload?.[0]?.payload?.label ?? ""}
              formatter={(v) => [`${v}`, "Score"]}
            />
            <Line
              type="monotone"
              dataKey="score"
              stroke="var(--accent)"
              strokeWidth={2.5}
              dot={{ r: 4, fill: "var(--accent)", strokeWidth: 0 }}
              activeDot={{ r: 6 }}
              isAnimationActive={!reduce}
              animationDuration={900}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
