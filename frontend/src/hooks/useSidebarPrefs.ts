"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";

const KEY = "interviewra_sidebar";
export const SIDEBAR_MIN = 220;
export const SIDEBAR_MAX = 440;
export const SIDEBAR_DEFAULT = 288;
const DEFAULTS = { open: false, width: SIDEBAR_DEFAULT };

const listeners = new Set<() => void>();
let memory: string | null = null; // used when localStorage is unavailable

function read(): string {
  try {
    return window.localStorage.getItem(KEY) ?? memory ?? "";
  } catch {
    return memory ?? "";
  }
}

function write(value: { open: boolean; width: number }) {
  const raw = JSON.stringify(value);
  memory = raw;
  try {
    window.localStorage.setItem(KEY, raw);
  } catch {
    /* ignore */
  }
  listeners.forEach((l) => l());
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  window.addEventListener("storage", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}

export const clampWidth = (w: number) => Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, Math.round(w)));

/** Desktop sidebar state (hidden by default, drag-resizable), remembered in localStorage. */
export function useSidebarPrefs() {
  const raw = useSyncExternalStore(subscribe, read, () => "");
  const prefs = useMemo(() => {
    try {
      const p = JSON.parse(raw) as Partial<typeof DEFAULTS>;
      return { open: p.open === true, width: clampWidth(typeof p.width === "number" ? p.width : SIDEBAR_DEFAULT) };
    } catch {
      return DEFAULTS;
    }
  }, [raw]);

  const setOpen = useCallback((open: boolean) => write({ ...prefs, open }), [prefs]);
  const setWidth = useCallback((width: number) => write({ ...prefs, width: clampWidth(width) }), [prefs]);
  return { ...prefs, setOpen, setWidth };
}
