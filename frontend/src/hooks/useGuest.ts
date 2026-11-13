"use client";

import { useContext } from "react";

import { GuestContext, type GuestContextValue } from "@/components/providers/GuestProvider";

/**
 * The current user. On first load (no token) a silent guest account is created via POST /auth/guest
 * and its token is stored under `interviewra_token`. Returns { user, isGuest, loading, error, refresh, setSession, logout }.
 */
export function useGuest(): GuestContextValue {
  const ctx = useContext(GuestContext);
  if (!ctx) throw new Error("useGuest must be used inside <GuestProvider>");
  return ctx;
}
