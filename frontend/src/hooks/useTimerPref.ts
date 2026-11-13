"use client";

import { useCallback, useSyncExternalStore } from "react";

const KEY = "interviewra_timer";
const listeners = new Set<() => void>();
let memory = false;

function read(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return memory;
  }
}
function subscribe(cb: () => void) {
  listeners.add(cb);
  window.addEventListener("storage", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}

/** "Show a per-question timer" preference (set on the setup page, can be turned off in the chat). */
export function useTimerPref(): [boolean, (on: boolean) => void] {
  const on = useSyncExternalStore(subscribe, read, () => false);
  const set = useCallback((value: boolean) => {
    memory = value;
    try {
      window.localStorage.setItem(KEY, value ? "1" : "0");
    } catch {
      /* ignore */
    }
    listeners.forEach((l) => l());
  }, []);
  return [on, set];
}
