import { API_BASE, ApiError, authHeaders, canRefresh, networkError, refreshToken, toApiError } from "@/lib/api";
import type { DoneEvent, SessionEvent, StreamErrorEvent, TokenEvent, ToolEvent } from "@/types";

export interface SSEHandlers {
  onSession?: (data: SessionEvent) => void;
  onToken?: (data: TokenEvent) => void;
  onToolEvent?: (data: ToolEvent) => void;
  onDone?: (data: DoneEvent) => void;
  onError?: (data: StreamErrorEvent) => void;
}

export interface ParsedEvent {
  event: string;
  data: unknown;
}

/** Split a text buffer into complete SSE events (`event: x\ndata: {json}\n\n`); `rest` is the unfinished tail. */
export function parseSSEBuffer(buffer: string): { events: ParsedEvent[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const blocks = normalized.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: ParsedEvent[] = [];
  for (const block of blocks) {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    }
    if (dataLines.length === 0) continue;
    try {
      events.push({ event, data: JSON.parse(dataLines.join("\n")) });
    } catch {
      /* ignore a malformed event instead of breaking the stream */
    }
  }
  return { events, rest };
}

function dispatch({ event, data }: ParsedEvent, h: SSEHandlers): "done" | "error" | null {
  switch (event) {
    case "session": h.onSession?.(data as SessionEvent); return null;
    case "token": h.onToken?.(data as TokenEvent); return null;
    case "tool_event": h.onToolEvent?.(data as ToolEvent); return null;
    case "done": h.onDone?.(data as DoneEvent); return "done";
    case "error": h.onError?.(data as StreamErrorEvent); return "error";
    default: return null;
  }
}

/**
 * POST `path` and consume the Server-Sent Events response, calling a handler per event.
 * Rejects with ApiError if the request itself fails (401, 429, 409 ...); errors that happen
 * mid-stream arrive through `onError`. Resolves when the stream ends. Abort with `signal`.
 */
export async function streamSSE(path: string, body: unknown, handlers: SSEHandlers, signal?: AbortSignal): Promise<void> {
  const open = () =>
    fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { Accept: "text/event-stream", "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body ?? {}),
      signal,
    });
  let res: Response;
  try {
    res = await open();
    if (res.status === 401) {
      const err = await toApiError(res.clone());
      if (canRefresh(path, err) && (await refreshToken())) res = await open(); // expired token: refresh once, retry
    }
  } catch {
    if (signal?.aborted) return;
    throw networkError();
  }
  if (!res.ok) throw await toApiError(res);
  if (!res.body) throw new ApiError(res.status, "no_stream", "The server did not send a stream.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parsed = parseSSEBuffer(buffer);
      buffer = parsed.rest;
      for (const ev of parsed.events) if (dispatch(ev, handlers)) finished = true;
    }
    buffer += decoder.decode();
    for (const ev of parseSSEBuffer(buffer + "\n\n").events) if (dispatch(ev, handlers)) finished = true;
  } catch {
    if (signal?.aborted) return;
    handlers.onError?.({ code: "stream_interrupted", message: "The connection was interrupted. Please try again." });
    return;
  } finally {
    reader.releaseLock();
  }
  if (!finished && !signal?.aborted) {
    handlers.onError?.({ code: "stream_interrupted", message: "The connection was interrupted. Please try again." });
  }
}
