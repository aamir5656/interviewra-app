import type { ApiErrorBody } from "@/types";

export const TOKEN_KEY = "interviewra_token";
const API_PREFIX = "/api/v1";
const DEFAULT_ORIGIN = "http://localhost:8000";
const WAKING_AFTER_MS = 4_000; // a request slower than this probably hit a sleeping free-tier server
const REQUEST_TIMEOUT_MS = 90_000;

/** NEXT_PUBLIC_API_URL is the backend origin; "/api/v1" is added here (and never doubled). */
function resolveBase(): string {
  const origin = (process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_ORIGIN).trim().replace(/\/+$/, "");
  return origin.replace(/\/api\/v1$/, "") + API_PREFIX;
}
export const API_BASE = resolveBase();

// ---------- token storage (localStorage can throw in private mode: never let that crash the app) ----------

export function getToken(): string | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* ignore */
  }
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

// ---------- errors ----------

export class ApiError extends Error {
  readonly status: number; // 0 = the server could not be reached
  readonly code: string;
  readonly requestId?: string;
  readonly retryAfter?: number; // seconds, from the Retry-After header on 429

  constructor(status: number, code: string, message: string, requestId?: string, retryAfter?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.retryAfter = retryAfter;
  }

  get isRateLimited(): boolean {
    return this.status === 429 || this.code === "rate_limited";
  }
  get isUnauthorized(): boolean {
    return this.status === 401;
  }
  get isNetworkError(): boolean {
    return this.status === 0;
  }
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  const e = (value as ApiErrorBody | null)?.error;
  return !!e && typeof e.code === "string" && typeof e.message === "string";
}

/** Turn a failed Response into an ApiError using the contract error shape. */
export async function toApiError(res: Response): Promise<ApiError> {
  const retry = Number(res.headers.get("Retry-After"));
  const retryAfter = Number.isFinite(retry) && retry > 0 ? retry : undefined;
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* not JSON */
  }
  if (isErrorBody(body)) {
    return new ApiError(res.status, body.error.code, body.error.message, body.error.request_id, retryAfter);
  }
  return new ApiError(res.status, "http_error", res.statusText || "Request failed", undefined, retryAfter);
}

export function networkError(): ApiError {
  return new ApiError(0, "network_error", "Can't reach the server. Check your connection and try again.");
}

// ---------- "server is waking up" detection (free hosting sleeps when idle) ----------

const listeners = new Set<() => void>();
let slowRequests = 0;

function bumpSlow(delta: number): void {
  slowRequests = Math.max(0, slowRequests + delta);
  listeners.forEach((l) => l());
}

export function subscribeServerStatus(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** true while at least one request has been running longer than WAKING_AFTER_MS */
export function isServerWaking(): boolean {
  return slowRequests > 0;
}

// ---------- fetch wrapper ----------

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

interface RequestOptions {
  signal?: AbortSignal;
}

// ---------- silent token refresh (an expired token is swapped once, then the request is retried) ----------

const NO_REFRESH_PATHS = ["/auth/refresh", "/auth/login", "/auth/register", "/auth/guest"];
let refreshing: Promise<boolean> | null = null;

async function doRefresh(): Promise<boolean> {
  if (!getToken()) return false;
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { Accept: "application/json", ...authHeaders() },
    });
    if (!res.ok) return false;
    const data = (await res.json()) as { access_token?: string };
    if (!data.access_token) return false;
    setToken(data.access_token);
    return true;
  } catch {
    return false;
  }
}

/** One refresh at a time, shared by every request that hits an expired token. Resolves true when a new token is stored. */
export function refreshToken(): Promise<boolean> {
  refreshing ??= doRefresh().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

export function canRefresh(path: string, err: unknown): boolean {
  return err instanceof ApiError && err.code === "token_expired" && !NO_REFRESH_PATHS.includes(path);
}

async function request<T>(method: string, path: string, body?: unknown, opts: RequestOptions = {}): Promise<T> {
  try {
    return await send<T>(method, path, body, opts);
  } catch (err) {
    if (canRefresh(path, err) && (await refreshToken())) return send<T>(method, path, body, opts);
    throw err;
  }
}

async function send<T>(method: string, path: string, body?: unknown, opts: RequestOptions = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  opts.signal?.addEventListener("abort", () => controller.abort(), { once: true });
  let slow = false;
  const wakingTimer = setTimeout(() => {
    slow = true;
    bumpSlow(1);
  }, WAKING_AFTER_MS);

  try {
    const headers: Record<string, string> = { Accept: "application/json", ...authHeaders() };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let res: Response;
    try {
      res = await fetch(`${API_BASE}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (err) {
      if (opts.signal?.aborted) throw err; // the caller cancelled on purpose
      throw networkError();
    }
    if (!res.ok) throw await toApiError(res);
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  } finally {
    clearTimeout(timeout);
    clearTimeout(wakingTimer);
    if (slow) bumpSlow(-1);
  }
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>("GET", path, undefined, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>("POST", path, body ?? {}, opts),
  patch: <T>(path: string, body: unknown, opts?: RequestOptions) => request<T>("PATCH", path, body, opts),
  delete: <T = void>(path: string, opts?: RequestOptions) => request<T>("DELETE", path, undefined, opts),
};
