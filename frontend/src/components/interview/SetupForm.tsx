"use client";

import { motion, useReducedMotion } from "framer-motion";
import { Clock, Loader2, Play, Timer, WifiOff } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { ResumeUpload } from "@/components/interview/ResumeUpload";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { useGuest } from "@/hooks/useGuest";
import { useInterview } from "@/hooks/useInterview";
import { useTimerPref } from "@/hooks/useTimerPref";
import { LEVELS, LIMITS, MINUTES_PER_QUESTION, ROLES, TYPES } from "@/lib/interview";
import { cn } from "@/lib/utils";
import type { InterviewType, Level } from "@/types";

const optionCard =
  "flex h-full cursor-pointer flex-col gap-0.5 rounded-xl border border-border bg-card px-3.5 py-3 text-sm transition-[border-color,background-color,transform] duration-200 hover:border-primary/60 active:scale-[0.98] peer-checked:border-primary peer-checked:bg-primary/10 peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-background";

export function SetupForm() {
  const { loading: guestLoading, error: guestError, refresh } = useGuest();
  const { start } = useInterview({ abortOnUnmount: "until-session" });
  const reduce = useReducedMotion();
  const [role, setRole] = useState("");
  const [level, setLevel] = useState<Level>("junior");
  const [type, setType] = useState<InterviewType>("mixed");
  const [count, setCount] = useState<number>(LIMITS.countDefault);
  const [roleError, setRoleError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [resumeId, setResumeId] = useState<string | null>(null);
  const [resumeBusy, setResumeBusy] = useState(false);
  const [timerOn, setTimerOn] = useTimerPref();
  const onResume = useCallback((id: string | null, busy: boolean) => {
    setResumeId(id);
    setResumeBusy(busy);
  }, []);
  const roleInput = useRef<HTMLSelectElement>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  function validateRole(value: string): string | null {
    return (ROLES as readonly string[]).includes(value) ? null : "Please choose a role from the list.";
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (submitting) return;
    const problem = validateRole(role);
    setRoleError(problem);
    if (problem) {
      roleInput.current?.focus();
      return;
    }
    setSubmitting(true);
    const ok = await start({ role_name: role, level, interview_type: type, question_count: count, ...(resumeId ? { resume_id: resumeId } : {}) });
    if (!ok && mounted.current) setSubmitting(false); // on success the page navigates to the interview
  }

  const offline = !!guestError && !guestLoading;
  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-10 sm:px-6 sm:py-14">
      <motion.div
        initial={reduce ? false : { opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
      >
        <h1 className="text-3xl font-bold sm:text-4xl">Set up your interview</h1>
        <p className="mt-2 text-muted-foreground">Tell Alex what you are preparing for. No signup needed.</p>

        <form onSubmit={onSubmit} noValidate className="mt-8 space-y-8">
          <div className="space-y-3">
            <Label htmlFor="role">Role you are practicing for</Label>
            <select
              id="role"
              ref={roleInput}
              value={role}
              required
              aria-invalid={!!roleError}
              aria-describedby={roleError ? "role-error" : undefined}
              onChange={(e) => {
                setRole(e.target.value);
                setRoleError(validateRole(e.target.value));
              }}
              className="flex h-11 w-full min-w-0 cursor-pointer rounded-lg border border-input bg-card px-3.5 py-2 text-base outline-none transition-[border-color,box-shadow] focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40 aria-invalid:border-destructive aria-invalid:ring-destructive/30 md:text-sm"
            >
              <option value="" disabled>
                Choose a role…
              </option>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            {roleError && (
              <p id="role-error" role="alert" className="text-sm text-destructive">
                {roleError}
              </p>
            )}
          </div>

          <fieldset className="space-y-3">
            <legend className="text-sm font-medium">Level</legend>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {LEVELS.map((l) => (
                <label key={l.value} className="block">
                  <input type="radio" name="level" value={l.value} checked={level === l.value} onChange={() => setLevel(l.value)} className="peer sr-only" />
                  <span className={optionCard}>
                    <span className="font-medium">{l.label}</span>
                    <span className="text-xs text-muted-foreground">{l.hint}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset className="space-y-3">
            <legend className="text-sm font-medium">Interview type</legend>
            <div className="grid grid-cols-2 gap-2">
              {TYPES.map((t) => (
                <label key={t.value} className="block">
                  <input type="radio" name="type" value={t.value} checked={type === t.value} onChange={() => setType(t.value)} className="peer sr-only" />
                  <span className={optionCard}>
                    <span className="font-medium">{t.label}</span>
                    <span className="text-xs text-muted-foreground">{t.hint}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Label htmlFor="count">Number of questions</Label>
              <span className="flex items-center gap-2 text-sm">
                <span className="font-heading text-lg font-semibold">{count}</span>
                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Clock className="size-3.5" aria-hidden />~{count * MINUTES_PER_QUESTION} min
                </span>
              </span>
            </div>
            <input
              id="count"
              type="range"
              min={LIMITS.countMin}
              max={LIMITS.countMax}
              step={1}
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
              aria-valuetext={`${count} questions`}
              className="h-2 w-full cursor-pointer accent-[var(--accent)]"
            />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>{LIMITS.countMin}</span>
              <span>{LIMITS.countMax}</span>
            </div>
          </div>

          <ResumeUpload onChange={onResume} />

          <div className="flex items-center justify-between gap-4 rounded-xl border border-border bg-card px-4 py-3">
            <div className="flex items-start gap-3">
              <Timer className="mt-0.5 size-5 text-muted-foreground" aria-hidden />
              <div>
                <p id="timer-label" className="text-sm font-medium">
                  Per-question timer
                </p>
                <p className="text-xs text-muted-foreground">A gentle {MINUTES_PER_QUESTION}-minute countdown. It never stops you from answering.</p>
              </div>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={timerOn}
              aria-labelledby="timer-label"
              onClick={() => setTimerOn(!timerOn)}
              className={cn(
                "relative h-6 w-11 shrink-0 rounded-full border border-border transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                timerOn ? "bg-primary" : "bg-muted",
              )}
            >
              <span className={cn("absolute top-0.5 left-0.5 size-4.5 rounded-full bg-background shadow transition-transform", timerOn && "translate-x-5")} />
            </button>
          </div>

          {offline && (
            <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-destructive/40 bg-destructive/10 p-3 text-sm">
              <span className="flex items-center gap-2">
                <WifiOff className="size-4 shrink-0" aria-hidden />
                Can&apos;t reach the server yet.
              </span>
              <Button type="button" size="sm" variant="outline" onClick={() => void refresh()}>
                Retry
              </Button>
            </div>
          )}

          <Button type="submit" size="lg" disabled={submitting || guestLoading || offline || resumeBusy} className={cn("w-full")}>
            {submitting ? (
              <>
                <Loader2 className="animate-spin" aria-hidden /> Starting your interview…
              </>
            ) : resumeBusy ? (
              <>
                <Loader2 className="animate-spin" aria-hidden /> Preparing your resume…
              </>
            ) : (
              <>
                <Play aria-hidden /> Start interview
              </>
            )}
          </Button>
        </form>
      </motion.div>
    </div>
  );
}
