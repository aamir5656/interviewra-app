"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useSyncExternalStore } from "react";

import { notifySessionsChanged } from "@/hooks/useSessions";
import { streamSSE } from "@/lib/sse";
import { toastError } from "@/lib/errors";
import type { InterviewCreate, SessionDetail } from "@/types";

export interface ChatItem {
  /** server message id once saved; "local-N" / "pending-N" while a turn is in flight */
  id: string;
  role: "user" | "assistant";
  content: string;
}

export interface InterviewState {
  sessionId: string | null;
  messages: ChatItem[];
  streaming: boolean;
  /** friendly label of the tool the interviewer is using right now ("Choosing the next topic") */
  toolHint: string | null;
  readyToEnd: boolean;
  /** set when starting failed after the session event (the server removes the empty session) */
  failure: { code: string; message: string } | null;
}

const INITIAL: InterviewState = { sessionId: null, messages: [], streaming: false, toolHint: null, readyToEnd: false, failure: null };
const ABORT_DELAY_MS = 150; // survives React strict-mode's mount/unmount/mount in development

// The run lives outside React: starting an interview navigates to /interview/[id] while the first reply is still
// streaming, so the stream must keep going across the page change.
let state: InterviewState = INITIAL;
let controller: AbortController | null = null;
let pendingAbort: ReturnType<typeof setTimeout> | null = null;
let seq = 0;
const listeners = new Set<() => void>();

function set(patch: Partial<InterviewState> | ((s: InterviewState) => Partial<InterviewState>)): void {
  state = { ...state, ...(typeof patch === "function" ? patch(state) : patch) };
  listeners.forEach((l) => l());
}
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
};
const getSnapshot = () => state;
const getServerSnapshot = () => INITIAL;

const pendingItem = (): ChatItem => ({ id: `pending-${++seq}`, role: "assistant", content: "" });

function appendToken(messages: ChatItem[], text: string): ChatItem[] {
  const last = messages[messages.length - 1];
  if (!last || last.role !== "assistant") return messages;
  return [...messages.slice(0, -1), { ...last, content: last.content + text }];
}

function finalize(messages: ChatItem[], messageId: string): ChatItem[] {
  const last = messages[messages.length - 1];
  if (!last || last.role !== "assistant") return messages;
  return [...messages.slice(0, -1), { ...last, id: messageId }];
}

/** A failed turn leaves nothing on the server, so remove its optimistic messages (the user can resend). */
function dropUnsaved(messages: ChatItem[]): ChatItem[] {
  const kept = messages.filter((m) => !m.id.startsWith("pending-"));
  const last = kept[kept.length - 1];
  return last && last.role === "user" && last.id.startsWith("local-") ? kept.slice(0, -1) : kept;
}

async function run(path: string, body: unknown, kind: "start" | "answer", onSession?: (id: string) => void): Promise<boolean> {
  controller?.abort();
  const ctl = new AbortController();
  controller = ctl;
  let failed = false;
  const fail = (err: unknown) => {
    failed = true;
    toastError(err);
    if (kind === "start") {
      const e = err as { code?: string; message?: string };
      set({ failure: { code: e.code ?? "error", message: e.message ?? "Something went wrong." } });
    }
  };
  try {
    await streamSSE(
      path,
      body,
      {
        onSession: (d) => {
          set({ sessionId: d.session_id });
          onSession?.(d.session_id);
        },
        onToken: (d) => set((s) => ({ toolHint: null, messages: appendToken(s.messages, d.text) })),
        onToolEvent: (d) => set({ toolHint: d.label }),
        onDone: (d) => { notifySessionsChanged(); set((s) => ({ readyToEnd: d.ready_to_end, toolHint: null, messages: finalize(s.messages, d.message_id) })); },
        onError: fail,
      },
      ctl.signal,
    );
  } catch (err) {
    if (!ctl.signal.aborted) fail(err);
  } finally {
    if (controller === ctl) controller = null;
  }
  if (ctl.signal.aborted) failed = true; // the user left: no toast, but nothing was kept on the server either
  set((s) => ({ streaming: false, toolHint: null, messages: failed ? dropUnsaved(s.messages) : s.messages }));
  return !failed;
}

export interface UseInterviewOptions {
  /** "always" (default): abort the stream when the component unmounts. "until-session": only before the session event. */
  abortOnUnmount?: "always" | "until-session";
}

export function useInterview({ abortOnUnmount = "always" }: UseInterviewOptions = {}) {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const router = useRouter();

  useEffect(() => {
    if (pendingAbort) {
      clearTimeout(pendingAbort);
      pendingAbort = null;
    }
    return () => {
      pendingAbort = setTimeout(() => {
        pendingAbort = null;
        if (controller && (abortOnUnmount === "always" || !state.sessionId)) controller.abort();
      }, ABORT_DELAY_MS);
    };
  }, [abortOnUnmount]);

  /** POST /interviews: the `session` event navigates to /interview/[id] while the first question keeps streaming. */
  const start = useCallback(
    (config: InterviewCreate): Promise<boolean> => {
      set({ ...INITIAL, streaming: true, messages: [pendingItem()] });
      return run("/interviews", config, "start", (id) => router.replace(`/interview/${id}`));
    },
    [router],
  );

  /** POST /interviews/{id}/answer. Resolves false when the turn failed (the text can be put back in the composer). */
  const sendAnswer = useCallback((text: string): Promise<boolean> => {
    const { sessionId, streaming } = state;
    if (!sessionId || streaming) return Promise.resolve(false);
    set((s) => ({
      streaming: true,
      toolHint: null,
      messages: [...s.messages, { id: `local-${++seq}`, role: "user", content: text }, pendingItem()],
    }));
    return run(`/interviews/${sessionId}/answer`, { content: text }, "answer");
  }, []);

  /** Load a saved interview into the chat (does nothing while that interview is streaming). */
  const hydrate = useCallback((detail: SessionDetail) => {
    if (state.streaming && state.sessionId === detail.id) return;
    set({
      sessionId: detail.id,
      streaming: false,
      toolHint: null,
      failure: null,
      readyToEnd: detail.ready_to_end || detail.status === "completed",
      messages: detail.messages
        .filter((m): m is SessionDetail["messages"][number] & { role: "user" | "assistant" } => m.role === "user" || m.role === "assistant")
        .map((m) => ({ id: m.id, role: m.role, content: m.content })),
    });
  }, []);

  const abort = useCallback(() => controller?.abort(), []);

  return { ...snapshot, start, sendAnswer, hydrate, abort };
}
