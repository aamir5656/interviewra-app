import { toast } from "sonner";

import { ApiError } from "@/lib/api";

const FRIENDLY: Record<string, string> = {
  llm_unavailable: "The AI is busy right now. Please try again in a minute.",
  llm_not_configured: "The AI service is not set up on the server yet.",
  llm_bad_json: "The AI sent a confusing answer. Please try again.",
  llm_empty: "The AI sent an empty reply. Please try again.",
  network_error: "Can't reach the server. Check your connection and try again.",
  stream_interrupted: "The connection was interrupted. Please try again.",
  interview_finished: "This interview is finished. Get your report instead.",
  session_not_active: "This interview has already ended.",
};

/** 4h 5m / 12m / 30s: used for the Retry-After hint on 429 errors. */
export function formatRetryAfter(seconds: number): string {
  const total = Math.max(1, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${total}s`;
}

export interface ErrorLike {
  code: string;
  message: string;
  retryAfter?: number;
}

export function friendlyMessage(code: string, message: string): string {
  return FRIENDLY[code] ?? message;
}

/** Friendly toast for an ApiError or an SSE error event. Rate limits show when the limit resets. */
export function toastError(err: unknown): void {
  const e: ErrorLike =
    err instanceof ApiError
      ? { code: err.code, message: err.message, retryAfter: err.retryAfter }
      : typeof err === "object" && err !== null && "code" in err && "message" in err
        ? (err as ErrorLike)
        : { code: "unknown", message: "Something went wrong. Please try again." };

  if (e.code === "rate_limited") {
    const hint = e.retryAfter && !/resets in/i.test(e.message) ? ` Try again in ${formatRetryAfter(e.retryAfter)}.` : "";
    toast.error("Daily limit reached", { description: e.message + hint });
    return;
  }
  toast.error(friendlyMessage(e.code, e.message));
}
