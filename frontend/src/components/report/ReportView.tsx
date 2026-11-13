"use client";

import { Download, Loader2, Plus } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { SavePrompt } from "@/components/layout/SavePrompt";
import { CategoryBars } from "@/components/report/CategoryBars";
import { InsightLists, TopicChips } from "@/components/report/InsightLists";
import { QuestionBreakdown } from "@/components/report/QuestionBreakdown";
import { RadarChartCard } from "@/components/report/RadarChartCard";
import { ScoreCard } from "@/components/report/ScoreCard";
import { buttonVariants, Button } from "@/components/ui/button";
import { useGuest } from "@/hooks/useGuest";
import { ApiError, api } from "@/lib/api";
import { toastError } from "@/lib/errors";
import type { InterviewSession, Report } from "@/types";

/** Full report page body: loads GET /interviews/{id}/report and renders it with real components. */
export function ReportView({ id }: { id: string }) {
  const { loading: guestLoading } = useGuest();
  const [report, setReport] = useState<Report | null>(null);
  const [meta, setMeta] = useState<InterviewSession | null>(null);
  const [missing, setMissing] = useState<null | "no-report" | "not-found">(null);

  useEffect(() => {
    if (guestLoading) return;
    api
      .get<Report>(`/interviews/${id}/report`)
      .then(setReport)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) setMissing(err.code === "report_not_found" ? "no-report" : "not-found");
        else toastError(err);
      });
    api.get<InterviewSession>(`/interviews/${id}`).then(setMeta, () => undefined); // title is a nicety
  }, [guestLoading, id]);

  if (missing === "not-found") {
    return (
      <div className="mx-auto flex max-w-xl flex-col items-center gap-4 px-4 py-20 text-center">
        <h1 className="text-3xl font-bold">Not found</h1>
        <p className="text-muted-foreground">This report does not exist or it belongs to another account.</p>
        <Link href="/history" className={buttonVariants({ variant: "outline" })}>
          Go to history
        </Link>
      </div>
    );
  }
  if (missing) {
    return (
      <div className="mx-auto flex max-w-xl flex-col items-center gap-4 px-4 py-20 text-center">
        <h1 className="text-3xl font-bold">No report yet</h1>
        <p className="text-muted-foreground">Finish the interview first, then your report appears here.</p>
        <Link href={`/interview/${id}`} className={buttonVariants({ variant: "outline" })}>
          Back to the interview
        </Link>
      </div>
    );
  }
  if (!report) {
    return (
      <div className="flex justify-center py-24">
        <Loader2 className="size-8 animate-spin text-muted-foreground" aria-label="Loading report" />
      </div>
    );
  }

  const subtitle = meta ? `${meta.title} · ${meta.level} ${meta.interview_type}` : undefined;
  return (
    <div className="mx-auto w-full max-w-3xl space-y-4 px-4 py-8 sm:px-6 print:max-w-none print:px-0 print:py-0" id="report">
      <ScoreCard report={report} title={subtitle} />
      {report.is_fallback && (
        <p className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
          The detailed AI report could not be generated this time, so this is a simple estimate. Try another interview for a full report.
        </p>
      )}
      {!report.is_fallback && (
        <div className="grid gap-4 md:grid-cols-2 print:grid-cols-2">
          <CategoryBars scores={report.category_scores} />
          <RadarChartCard scores={report.category_scores} />
        </div>
      )}
      <QuestionBreakdown items={report.per_question} />
      <InsightLists strengths={report.strengths} weaknesses={report.weaknesses} tips={report.improvement_tips} />
      <TopicChips topics={report.recommended_topics} />

      <div className="flex flex-col gap-3 pt-2 sm:flex-row print:hidden">
        <Link href="/interview/new" className={buttonVariants({ size: "lg" })}>
          <Plus aria-hidden /> Start another interview
        </Link>
        <Button size="lg" variant="outline" onClick={() => window.print()}>
          <Download aria-hidden /> Download report
        </Button>
      </div>
      <SavePrompt />
    </div>
  );
}
