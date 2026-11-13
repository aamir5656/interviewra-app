"use client";

import { motion, useReducedMotion } from "framer-motion";
import { ArrowRight, FileText, Loader2, SearchX } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { ChatWindow } from "@/components/chat/ChatWindow";
import { QuestionTimer } from "@/components/chat/QuestionTimer";
import { Composer } from "@/components/chat/Composer";
import { Button, buttonVariants } from "@/components/ui/button";
import { useGuest } from "@/hooks/useGuest";
import { useInterview } from "@/hooks/useInterview";
import { useTimerPref } from "@/hooks/useTimerPref";
import { ApiError, api } from "@/lib/api";
import { toastError } from "@/lib/errors";
import { MINUTES_PER_QUESTION, levelLabel, typeLabel } from "@/lib/interview";
import type { Report, SessionDetail } from "@/types";

type Phase = "loading" | "ready" | "missing" | "error";

export function InterviewRoom({ id }: { id: string }) {
  const router = useRouter();
  const reduce = useReducedMotion();
  const [timerOn, setTimerOn] = useTimerPref();
  const { loading: guestLoading } = useGuest();
  const chat = useInterview({ abortOnUnmount: "always" });
  const { hydrate } = chat;
  const [meta, setMeta] = useState<SessionDetail | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [ending, setEnding] = useState(false);
  const wasStreaming = useRef(false);

  const applyDetail = useCallback(
    (detail: SessionDetail, withMessages: boolean) => {
      setMeta(detail);
      if (withMessages) hydrate(detail);
      setPhase("ready");
    },
    [hydrate],
  );
  const onLoadError = useCallback((err: unknown) => {
    if (err instanceof ApiError && err.status === 404) setPhase("missing");
    else {
      toastError(err);
      setPhase("error");
    }
  }, []);

  // first load. When the interview was just started, its first reply is still streaming: keep that state.
  useEffect(() => {
    if (guestLoading) return;
    const withMessages = !(chat.sessionId === id && chat.streaming);
    api.get<SessionDetail>(`/interviews/${id}`).then((d) => applyDetail(d, withMessages), onLoadError);
    // run once per interview: later changes of the live chat state are handled by the effect below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [guestLoading, id, applyDetail, onLoadError]);

  // after every reply: refresh the progress ("Question X of N")
  useEffect(() => {
    if (wasStreaming.current && !chat.streaming && chat.sessionId === id) {
      api.get<SessionDetail>(`/interviews/${id}`).then((d) => applyDetail(d, false), onLoadError);
    }
    wasStreaming.current = chat.streaming;
  }, [chat.streaming, chat.sessionId, id, applyDetail, onLoadError]);

  async function getReport() {
    setEnding(true);
    try {
      await api.post<Report>(`/interviews/${id}/end`);
      router.push(`/interview/${id}/report`);
    } catch (err) {
      toastError(err);
      setEnding(false);
    }
  }

  const live = chat.sessionId === id;
  if (phase === "missing" || (phase === "error" && !live)) {
    const failed = chat.failure;
    return (
      <div className="mx-auto flex max-w-md flex-col items-center gap-4 px-4 py-24 text-center">
        <SearchX className="size-8 text-muted-foreground" aria-hidden />
        <h1 className="text-2xl font-bold">{failed ? "The interview could not start" : "Interview not found"}</h1>
        <p className="text-muted-foreground">
          {failed ? failed.message : "It may have been deleted, or it belongs to a different account."}
        </p>
        <Link href="/interview/new" className={buttonVariants()}>
          Start a new interview
        </Link>
      </div>
    );
  }

  const total = meta?.question_count ?? 0;
  const done = chat.readyToEnd || meta?.ready_to_end || meta?.status === "completed";
  const current = meta ? (done ? total : Math.min(Math.max(meta.current_question_index, 1), total)) : 0;
  const completed = meta?.status === "completed";
  const loadingHistory = phase === "loading" && !live;

  return (
    <div className="flex h-[calc(100dvh-6.5rem)] flex-col lg:h-[calc(100dvh-4rem)]">
      <div className="border-b border-border bg-background/90 px-4 py-3 sm:px-6">
        <div className="mx-auto w-full max-w-3xl">
          <div className="flex items-baseline justify-between gap-3">
            <h1 className="truncate font-heading text-base font-semibold sm:text-lg">{meta?.title ?? "Starting your interview…"}</h1>
            {meta && (
              <span className="shrink-0 text-xs text-muted-foreground">
                {levelLabel(meta.level)} · {typeLabel(meta.interview_type)}
              </span>
            )}
          </div>
          <div className="mt-2 flex items-center gap-3">
            <div
              role="progressbar"
              aria-label="Interview progress"
              aria-valuemin={0}
              aria-valuemax={total || 1}
              aria-valuenow={current}
              className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted"
            >
              <motion.div
                className="h-full origin-left rounded-full bg-primary"
                style={{ width: "100%" }}
                initial={false}
                animate={{ scaleX: total ? current / total : 0 }}
                transition={reduce ? { duration: 0 } : { duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
              />
            </div>
            <span className="shrink-0 text-xs font-medium tabular-nums">
              {!meta ? "…" : done ? "Interview complete" : `Question ${current} of ${total}`}
            </span>
            {timerOn && meta && !done && (
              <QuestionTimer
                resetKey={current}
                running={phase === "ready" && !chat.streaming}
                seconds={MINUTES_PER_QUESTION * 60}
                onHide={() => setTimerOn(false)}
              />
            )}
          </div>
        </div>
      </div>

      <ChatWindow messages={chat.messages} streaming={chat.streaming} toolHint={chat.toolHint} loading={loadingHistory} />

      {done ? (
        <div className="border-t border-border bg-background/90 px-4 py-4 sm:px-6">
          <div className="mx-auto flex w-full max-w-3xl flex-col items-center gap-2 text-center">
            {completed ? (
              <Link href={`/interview/${id}/report`} className={buttonVariants({ size: "lg" })}>
                <FileText aria-hidden /> View my report
              </Link>
            ) : (
              <>
                <Button size="lg" onClick={() => void getReport()} disabled={ending || chat.streaming}>
                  {ending ? <Loader2 className="animate-spin" aria-hidden /> : <ArrowRight aria-hidden />}
                  {ending ? "Writing your report…" : "Get my report"}
                </Button>
                <p className="text-xs text-muted-foreground">
                  {ending ? "This can take up to a minute. Please keep this page open." : "Alex is done asking questions."}
                </p>
              </>
            )}
          </div>
        </div>
      ) : (
        <Composer onSend={chat.sendAnswer} disabled={chat.streaming || phase !== "ready" || !live} />
      )}
    </div>
  );
}
