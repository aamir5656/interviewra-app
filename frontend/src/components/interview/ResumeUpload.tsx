"use client";

import { AlertTriangle, CheckCircle2, FileText, FileUp, Loader2, ShieldCheck, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type DragEvent, type KeyboardEvent } from "react";

import { toastError } from "@/lib/errors";
import { MAX_RESUME_MB, deleteResume, getResume, uploadResume, validateResumeFile } from "@/lib/resume";
import { cn } from "@/lib/utils";

export type ResumeState =
  | { phase: "empty" }
  | { phase: "uploading"; name: string; percent: number }
  | { phase: "reading"; name: string; id: string }
  | { phase: "ready"; name: string; id: string }
  | { phase: "failed"; name: string; id: string };

const POLL_MS = 1500;
const POLL_MAX = 40; // about a minute, then stop waiting

interface Props {
  /** Reports the resume id to use (only when the summary is ready) and whether the form should wait. */
  onChange: (resumeId: string | null, busy: boolean) => void;
}

export function ResumeUpload({ onChange }: Props) {
  const [state, setState] = useState<ResumeState>({ phase: "empty" });
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);
  const run = useRef(0); // invalidates polling/upload callbacks after remove or a new file

  const update = useCallback(
    (next: ResumeState) => {
      setState(next);
      onChange(next.phase === "ready" ? next.id : null, next.phase === "uploading" || next.phase === "reading");
    },
    [onChange],
  );

  useEffect(
    () => () => {
      run.current++;
      abort.current?.abort();
    },
    [],
  );

  async function poll(id: string, name: string, ticket: number) {
    for (let i = 0; i < POLL_MAX; i++) {
      await new Promise((r) => setTimeout(r, POLL_MS));
      if (ticket !== run.current) return;
      try {
        const r = await getResume(id);
        if (ticket !== run.current) return;
        if (r.failed) return update({ phase: "failed", name, id });
        if (r.ready) return update({ phase: "ready", name, id });
      } catch {
        /* keep trying until the limit */
      }
    }
    if (ticket === run.current) update({ phase: "failed", name, id });
  }

  async function handleFile(file: File | undefined) {
    if (!file) return;
    const problem = validateResumeFile(file);
    setError(problem);
    if (problem) return;
    const ticket = ++run.current;
    abort.current?.abort();
    abort.current = new AbortController();
    update({ phase: "uploading", name: file.name, percent: 0 });
    try {
      const res = await uploadResume(
        file,
        (percent) => ticket === run.current && setState({ phase: "uploading", name: file.name, percent }),
        abort.current.signal,
      );
      if (ticket !== run.current) return;
      if (res.failed) return update({ phase: "failed", name: res.filename, id: res.resume_id });
      if (res.ready) return update({ phase: "ready", name: res.filename, id: res.resume_id });
      update({ phase: "reading", name: res.filename, id: res.resume_id });
      void poll(res.resume_id, res.filename, ticket);
    } catch (err) {
      if (ticket !== run.current) return;
      update({ phase: "empty" });
      if ((err as { name?: string }).name !== "AbortError") {
        setError(err instanceof Error ? err.message : "Upload failed.");
        toastError(err);
      }
    }
  }

  async function remove() {
    const current = state;
    run.current++;
    abort.current?.abort();
    update({ phase: "empty" });
    setError(null);
    if (input.current) input.current.value = "";
    if (current.phase === "reading" || current.phase === "ready" || current.phase === "failed") {
      try {
        await deleteResume(current.id);
      } catch {
        /* already gone or offline: nothing to show */
      }
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    void handleFile(e.dataTransfer.files[0]);
  }
  function onKey(e: KeyboardEvent) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      input.current?.click();
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Resume (optional)</span>
        <span className="text-xs text-muted-foreground">PDF, up to {MAX_RESUME_MB} MB</span>
      </div>

      {state.phase === "empty" ? (
        <div
          role="button"
          tabIndex={0}
          aria-label="Upload your resume as a PDF"
          onClick={() => input.current?.click()}
          onKeyDown={onKey}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            "flex cursor-pointer flex-col items-center gap-1.5 rounded-xl border border-dashed border-border bg-card px-4 py-6 text-center text-sm transition-colors outline-none hover:border-primary/60 focus-visible:ring-2 focus-visible:ring-ring",
            dragging && "border-primary bg-primary/10",
          )}
        >
          <FileUp className="size-5 text-muted-foreground" aria-hidden />
          <span>
            <span className="font-medium text-primary">Choose a PDF</span> or drag it here
          </span>
          <span className="text-xs text-muted-foreground">Alex will ask about your own projects and skills.</span>
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card p-3.5">
          <div className="flex items-center gap-3">
            <FileText className="size-5 shrink-0 text-muted-foreground" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{state.name}</p>
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
                {state.phase === "uploading" && <>Uploading… {state.percent}%</>}
                {state.phase === "reading" && (
                  <>
                    <Loader2 className="size-3.5 animate-spin" aria-hidden /> Reading your resume…
                  </>
                )}
                {state.phase === "ready" && (
                  <>
                    <CheckCircle2 className="size-3.5 text-brand-2" aria-hidden /> Ready. Alex will tailor the questions to it.
                  </>
                )}
                {state.phase === "failed" && (
                  <>
                    <AlertTriangle className="size-3.5 text-amber-500" aria-hidden /> Could not be summarised. The interview will not be personalised.
                  </>
                )}
              </p>
            </div>
            <button
              type="button"
              onClick={() => void remove()}
              aria-label="Remove resume"
              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              <X className="size-4" />
            </button>
          </div>
          {state.phase === "uploading" && (
            <div
              role="progressbar"
              aria-label="Upload progress"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={state.percent}
              className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted"
            >
              <div className="h-full rounded-full bg-primary transition-[width] duration-150" style={{ width: `${state.percent}%` }} />
            </div>
          )}
        </div>
      )}

      <input ref={input} type="file" accept="application/pdf,.pdf" className="sr-only" tabIndex={-1} onChange={(e) => void handleFile(e.target.files?.[0])} />
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <p className="flex items-start gap-1.5 text-xs leading-relaxed text-muted-foreground">
        <ShieldCheck className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        Your resume is private to your account. Its text is sent to the AI service once to make a short summary (no contact details are kept in it). Remove it any time.
      </p>
    </div>
  );
}
