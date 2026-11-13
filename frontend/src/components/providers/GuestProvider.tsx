"use client";

import { createContext, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { ApiError, api, clearToken, getToken, setToken } from "@/lib/api";
import type { TokenResponse, User } from "@/types";

export interface GuestContextValue {
  user: User | null;
  isGuest: boolean;
  loading: boolean;
  error: ApiError | null;
  /** Re-run the bootstrap (retry after a network error, or reload the user). */
  refresh: () => Promise<void>;
  /** Store a token response (used by login/register in a later part). */
  setSession: (auth: TokenResponse) => void;
  /** Forget the token and continue as a fresh guest. */
  logout: () => Promise<void>;
}

export const GuestContext = createContext<GuestContextValue | null>(null);

let inflight: Promise<User> | null = null; // React strict mode runs effects twice: never create two guests

async function bootstrap(): Promise<User> {
  if (!inflight) {
    inflight = (async () => {
      if (getToken()) {
        try {
          return await api.get<User>("/auth/me");
        } catch (err) {
          if (!(err instanceof ApiError && err.isUnauthorized)) throw err; // server down: keep the token
          clearToken(); // expired or unknown account
        }
      }
      const res = await api.post<TokenResponse>("/auth/guest");
      setToken(res.access_token);
      return res.user;
    })().finally(() => {
      inflight = null;
    });
  }
  return inflight;
}

export function GuestProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setUser(await bootstrap());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, "network_error", "Something went wrong."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false; // first load: the state is set in promise callbacks, not synchronously in the effect
    bootstrap()
      .then((u) => {
        if (cancelled) return;
        setUser(u);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err : new ApiError(0, "network_error", "Something went wrong."));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const setSession = useCallback((auth: TokenResponse) => {
    setToken(auth.access_token);
    setUser(auth.user);
    setError(null);
  }, []);

  const logout = useCallback(async () => {
    clearToken();
    setUser(null);
    await refresh();
  }, [refresh]);

  const value = useMemo<GuestContextValue>(
    () => ({ user, isGuest: user?.is_guest ?? true, loading, error, refresh, setSession, logout }),
    [user, loading, error, refresh, setSession, logout],
  );
  return <GuestContext.Provider value={value}>{children}</GuestContext.Provider>;
}
