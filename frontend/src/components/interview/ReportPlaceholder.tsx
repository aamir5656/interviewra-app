"use client";

import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { buttonVariants } from "@/components/ui/button";
import { useGuest } from "@/hooks/useGuest";
import { ApiError, api } from "@/lib/api";
import type { Report } from "@/types";

/** Minimal report view. The full report UI (scores, charts, per-question feedback) replaces this in a later part. */
export function ReportPlaceholder({ id }: { id: string }) {
  const { loading: guestLoading } = useGuest();
  const [report, setReport] = useState<Report | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    if (guestLoading) return;
    api
      .get<Report>(`/interviews/${id}/report`)
      .then(setReport)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) setMissing(true);
      });
  }, [guestLoading, id]);

  return (
    <div className="mx-auto flex max-w-xl flex-col items-center gap-4 px-4 py-20 text-center">
      {missing ? (
        <>
          <h1 className="text-3xl font-bold">No report yet</h1>
          <Link href={`/interview/${id}`} className={buttonVariants({ variant: "outline" })}>
            Back to the interview
          </Link>
        </>
      ) : !report ? (
        <Loader2 className="size-8 animate-spin text-muted-foreground" aria-label="Loading report" />
      ) : (
        <>
          <p className="text-sm text-muted-foreground">Your overall score</p>
          <p className="font-heading text-7xl font-bold text-brand">{report.overall_score}</p>
          {report.is_fallback && (
            <p className="rounded-lg border border-border bg-card px-3 py-2 text-sm text-muted-foreground">
              The detailed AI report could not be generated this time.
            </p>
          )}
          <p className="text-muted-foreground">{report.summary}</p>
          <p className="text-xs text-muted-foreground">The full report (charts, per-question feedback, tips) arrives in a later part.</p>
          <Link href="/interview/new" className={buttonVariants()}>
            Start another interview
          </Link>
        </>
      )}
    </div>
  );
}
