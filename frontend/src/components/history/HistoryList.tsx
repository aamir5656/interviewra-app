"use client";

import { ArrowRight, Plus } from "lucide-react";
import Link from "next/link";

import { sessionHref } from "@/components/layout/Sidebar";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useGuest } from "@/hooks/useGuest";
import { useSessions } from "@/hooks/useSessions";
import { formatDate } from "@/lib/report";

const STATUS: Record<string, string> = { active: "In progress", completed: "Completed", abandoned: "Abandoned" };

export function HistoryList() {
  const { items, loading, error } = useSessions();
  const { isGuest } = useGuest();
  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6">
      <div className="flex items-center justify-between gap-3">
        <h1 className="font-heading text-2xl font-bold sm:text-3xl">Your interviews</h1>
        <Link href="/interview/new" className={buttonVariants()}>
          <Plus aria-hidden /> New
        </Link>
      </div>
      {isGuest && (
        <p className="mt-3 rounded-lg border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
          You are using a guest account. Sign up from the user icon at the top to keep your history forever.
        </p>
      )}
      <ul className="mt-6 space-y-3">
        {loading ? (
          [0, 1, 2].map((i) => <Skeleton key={i} className="h-20 w-full" />)
        ) : error && items.length === 0 ? (
          <li className="text-muted-foreground">Could not load your interviews. Try again in a moment.</li>
        ) : items.length === 0 ? (
          <li className="rounded-xl border border-dashed border-border p-8 text-center text-muted-foreground">No interviews yet.</li>
        ) : (
          items.map((s) => (
            <li key={s.id}>
              <Link
                href={sessionHref(s)}
                className="group flex items-center gap-4 rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/60 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{s.title}</p>
                  <p className="truncate text-sm text-muted-foreground">
                    {s.role_name} · {s.level} · {s.interview_type} · {formatDate(s.created_at)}
                  </p>
                </div>
                <span className="shrink-0 rounded-full bg-muted px-2.5 py-0.5 text-xs">{STATUS[s.status] ?? s.status}</span>
                <ArrowRight aria-hidden className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
              </Link>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
