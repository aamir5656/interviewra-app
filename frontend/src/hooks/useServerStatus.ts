"use client";

import { useSyncExternalStore } from "react";

import { isServerWaking, subscribeServerStatus } from "@/lib/api";

/** true while the backend is slow to answer (probably waking up from sleep). */
export function useServerWaking(): boolean {
  return useSyncExternalStore(subscribeServerStatus, isServerWaking, () => false);
}
