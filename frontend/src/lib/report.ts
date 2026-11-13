import type { CategoryScores } from "@/types";

export interface Tone {
  label: string;
  stroke: string;
  bar: string;
  text: string;
}

/** Colour and word for a 0-100 score (same bands as the evaluator rubric). */
export function scoreTone(score: number): Tone {
  if (score >= 80) return { label: "Strong", stroke: "stroke-brand", bar: "bg-brand", text: "text-brand" };
  if (score >= 60) return { label: "Meets the bar", stroke: "stroke-brand-2", bar: "bg-brand-2", text: "text-brand-2" };
  if (score >= 40) return { label: "Below the bar", stroke: "stroke-amber-500", bar: "bg-amber-500", text: "text-amber-500" };
  return { label: "Needs work", stroke: "stroke-destructive", bar: "bg-destructive", text: "text-destructive" };
}

export const CATEGORY_LABELS: Record<keyof CategoryScores, string> = {
  technical_accuracy: "Technical accuracy",
  communication: "Communication",
  depth: "Depth",
  problem_solving: "Problem solving",
};

export const CATEGORY_KEYS = Object.keys(CATEGORY_LABELS) as (keyof CategoryScores)[];

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
