import { AlertTriangle, CheckCircle2, Target } from "lucide-react";
import type { ReactNode } from "react";

function ListCard({ title, icon, items, tone }: { title: string; icon: ReactNode; items: string[]; tone: string }) {
  if (items.length === 0) return null;
  return (
    <section className="rounded-xl border border-border bg-card p-6 print:break-inside-avoid">
      <h2 className="flex items-center gap-2 font-heading text-lg font-semibold">
        <span className={tone}>{icon}</span> {title}
      </h2>
      <ul className="mt-3 space-y-2.5 text-sm leading-relaxed">
        {items.map((item, i) => (
          <li key={i} className="flex gap-2.5">
            <span aria-hidden className={`mt-2 size-1.5 shrink-0 rounded-full bg-current ${tone}`} />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function InsightLists({ strengths, weaknesses, tips }: { strengths: string[]; weaknesses: string[]; tips: string[] }) {
  return (
    <>
      <div className="grid gap-4 md:grid-cols-2 print:grid-cols-2">
        <ListCard title="Strengths" icon={<CheckCircle2 className="size-5" />} items={strengths} tone="text-brand-2" />
        <ListCard title="To improve" icon={<AlertTriangle className="size-5" />} items={weaknesses} tone="text-amber-500" />
      </div>
      <ListCard title="Tips for next time" icon={<Target className="size-5" />} items={tips} tone="text-brand" />
    </>
  );
}

export function TopicChips({ topics }: { topics: string[] }) {
  if (topics.length === 0) return null;
  return (
    <section className="rounded-xl border border-border bg-card p-6 print:break-inside-avoid">
      <h2 className="font-heading text-lg font-semibold">Study next</h2>
      <ul className="mt-3 flex flex-wrap gap-2">
        {topics.map((t) => (
          <li key={t} className="rounded-full border border-border bg-muted px-3 py-1 text-sm">
            {t}
          </li>
        ))}
      </ul>
    </section>
  );
}
