"use client";

import { BarChart3, LineChart, Plus, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { TrendChart } from "@/components/dashboard/TrendChart";
import { AuthDialog } from "@/components/layout/AuthDialog";
import { RadarChartCard } from "@/components/report/RadarChartCard";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useGuest } from "@/hooks/useGuest";
import { api } from "@/lib/api";
import { toastError } from "@/lib/errors";
import { scoreTone } from "@/lib/report";
import type { CategoryScores, DashboardStats } from "@/types";

function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-1 font-heading text-3xl font-bold tabular-nums">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function GuestTeaser() {
  const [open, setOpen] = useState(false);
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center gap-4 rounded-xl border border-border bg-card px-6 py-12 text-center">
      <BarChart3 className="size-9 text-brand" aria-hidden />
      <h1 className="font-heading text-2xl font-bold">Track your progress</h1>
      <p className="text-muted-foreground">
        Create a free account to see your score trend, your strongest and weakest skills, and what to practice next. Your guest interviews come with you.
      </p>
      <Button size="lg" onClick={() => setOpen(true)}>
        <Sparkles aria-hidden /> Create a free account
      </Button>
      <AuthDialog open={open} onOpenChange={setOpen} defaultTab="register" />
    </div>
  );
}

function Empty() {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center gap-4 rounded-xl border border-dashed border-border px-6 py-14 text-center">
      <LineChart className="size-9 text-muted-foreground" aria-hidden />
      <h2 className="font-heading text-xl font-semibold">No reports yet</h2>
      <p className="text-muted-foreground">Finish your first interview and your progress shows up here.</p>
      <Link href="/interview/new" className={buttonVariants({ size: "lg" })}>
        <Plus aria-hidden /> Start an interview
      </Link>
    </div>
  );
}

export function DashboardView() {
  const { isGuest, loading: guestLoading } = useGuest();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (guestLoading || isGuest) return;
    api
      .get<DashboardStats>("/dashboard/stats")
      .then(setStats)
      .catch((err: unknown) => {
        setFailed(true);
        toastError(err);
      });
  }, [guestLoading, isGuest]);

  const shell = "mx-auto w-full max-w-4xl px-4 py-8 sm:px-6";
  if (guestLoading) return <div className={shell}><Skeleton className="h-64 w-full" /></div>;
  if (isGuest) return <div className={`${shell} py-14`}><GuestTeaser /></div>;
  if (failed) return <div className={`${shell} text-center text-muted-foreground`}>Could not load your dashboard. Please refresh in a moment.</div>;
  if (!stats) {
    return (
      <div className={`${shell} space-y-4`}>
        <div className="grid gap-4 sm:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-24" />)}</div>
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }
  if (stats.interview_count === 0) return <div className={`${shell} py-14`}><Empty /></div>;

  const trend = stats.score_trend;
  const latest = trend[trend.length - 1]?.score ?? 0;
  const delta = trend.length > 1 ? latest - trend[trend.length - 2].score : null;
  const best = Math.max(...trend.map((p) => p.score));
  const cats: CategoryScores = {
    technical_accuracy: stats.category_averages.technical_accuracy ?? 0,
    communication: stats.category_averages.communication ?? 0,
    depth: stats.category_averages.depth ?? 0,
    problem_solving: stats.category_averages.problem_solving ?? 0,
  };
  const topCount = stats.top_weak_topics[0]?.count ?? 1;

  return (
    <div className={`${shell} space-y-4`}>
      <h1 className="font-heading text-2xl font-bold sm:text-3xl">Your progress</h1>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Interviews" value={stats.interview_count} hint="with a full report" />
        <Stat label="Average score" value={<span className={scoreTone(stats.average_score ?? 0).text}>{stats.average_score ?? "-"}</span>} />
        <Stat
          label="Latest score"
          value={latest}
          hint={delta === null ? undefined : `${delta >= 0 ? "+" : ""}${delta} vs previous`}
        />
        <Stat label="Best score" value={best} />
      </div>
      <TrendChart points={trend} />
      <div className="grid gap-4 md:grid-cols-2">
        <RadarChartCard scores={cats} title="Strengths and weaknesses" />
        <section className="rounded-xl border border-border bg-card p-6">
          <h2 className="font-heading text-lg font-semibold">Most common weak spots</h2>
          {stats.top_weak_topics.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">Nothing repeats yet. Nice.</p>
          ) : (
            <ul className="mt-4 space-y-4">
              {stats.top_weak_topics.map((t) => (
                <li key={t.topic}>
                  <div className="flex items-start justify-between gap-3 text-sm">
                    <span>{t.topic}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {t.count}×
                    </span>
                  </div>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
                    <div className="h-full rounded-full bg-amber-500" style={{ width: `${(t.count / topCount) * 100}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
