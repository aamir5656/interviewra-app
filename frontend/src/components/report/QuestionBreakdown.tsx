"use client";

import { ChevronDown, Lightbulb } from "lucide-react";
import { useState } from "react";

import { scoreTone } from "@/lib/report";
import { cn } from "@/lib/utils";
import type { PerQuestion } from "@/types";

function Item({ q, index, defaultOpen }: { q: PerQuestion; index: number; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const tone = scoreTone(q.score);
  const panelId = `q-panel-${index}`;
  return (
    <li className="border-b border-border last:border-b-0">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-start gap-3 py-4 text-left focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium">{index + 1}</span>
        <span className="min-w-0 flex-1 text-sm font-medium sm:text-base">
          {q.question}
          {q.critical_mistake && (
            <span className="ml-2 rounded-full bg-destructive/15 px-2 py-0.5 align-middle text-xs font-semibold text-destructive">Critical</span>
          )}
          {q.needed_prompting && !q.critical_mistake && (
            <span className="ml-2 rounded-full bg-amber-500/15 px-2 py-0.5 align-middle text-xs font-semibold text-amber-600">Needed a hint</span>
          )}
        </span>
        <span className={cn("shrink-0 text-sm font-semibold tabular-nums", tone.text)}>{q.score}</span>
        <ChevronDown aria-hidden className={cn("mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform print:hidden", open && "rotate-180")} />
      </button>
      <div
        id={panelId}
        className={cn("grid transition-[grid-template-rows] duration-300 print:grid-rows-[1fr]", open ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}
      >
        <div className="overflow-hidden">
          <div className="space-y-3 pb-5 pl-9 text-sm leading-relaxed">
            <p>
              <span className="text-muted-foreground">Your answer: </span>
              {q.answer_summary}
            </p>
            <p>{q.feedback}</p>
            <p className="flex gap-2 rounded-lg border border-border bg-muted p-3">
              <Lightbulb aria-hidden className="mt-0.5 size-4 shrink-0 text-brand" />
              <span>
                <span className="font-medium">A stronger answer: </span>
                {q.better_answer_hint}
              </span>
            </p>
          </div>
        </div>
      </div>
    </li>
  );
}

/** Accordion with one row per question (all rows expand when printing). */
export function QuestionBreakdown({ items }: { items: PerQuestion[] }) {
  if (items.length === 0) return null;
  return (
    <section className="rounded-xl border border-border bg-card px-6 py-2">
      <h2 className="pt-4 font-heading text-lg font-semibold">Question by question</h2>
      <ul>
        {items.map((q, i) => (
          <Item key={i} q={q} index={i} defaultOpen={i === 0} />
        ))}
      </ul>
    </section>
  );
}
