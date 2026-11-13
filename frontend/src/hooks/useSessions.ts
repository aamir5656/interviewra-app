"use client";

import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { useGuest } from "@/hooks/useGuest";
import { api } from "@/lib/api";
import type { InterviewSession, SessionList } from "@/types";

const EVENT = "interviewra:sessions-changed";

/** Tell every mounted list (sidebar, history page) to reload, e.g. after a rename or a new title. */
export function notifySessionsChanged(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(EVENT));
}

/** The current user's interviews, newest first. Reloads on navigation, on login/register and on notifySessionsChanged(). */
export function useSessions() {
  const { user, loading: guestLoading } = useGuest();
  const pathname = usePathname();
  const userId = user?.id;
  const [items, setItems] = useState<InterviewSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const latest = useRef(0); // only the newest request may update the list (a slow reply for a previous account is ignored)
  const load = useCallback(() => {
    const ticket = ++latest.current;
    return api
      .get<SessionList>("/interviews?limit=50")
      .then((d) => {
        if (ticket !== latest.current) return;
        setItems(d.items);
        setError(false);
      })
      .catch(() => ticket === latest.current && setError(true))
      .finally(() => ticket === latest.current && setLoading(false));
  }, []);

  // Never show another account's list: drop everything the moment the signed-in user changes.
  const [owner, setOwner] = useState(userId);
  if (owner !== userId) {
    setOwner(userId);
    setItems([]);
    setLoading(true);
  }

  useEffect(() => {
    if (guestLoading || !userId) return;
    void load();
  }, [guestLoading, userId, pathname, load]);

  useEffect(() => {
    const handler = () => void load();
    window.addEventListener(EVENT, handler);
    return () => window.removeEventListener(EVENT, handler);
  }, [load]);

  const rename = useCallback(async (id: string, title: string) => {
    const updated = await api.patch<InterviewSession>(`/interviews/${id}`, { title });
    setItems((prev) => prev.map((s) => (s.id === id ? { ...s, title: updated.title } : s)));
    notifySessionsChanged();
  }, []);

  const remove = useCallback(async (id: string) => {
    await api.delete<void>(`/interviews/${id}`);
    setItems((prev) => prev.filter((s) => s.id !== id));
    notifySessionsChanged();
  }, []);

  return { items, loading, error, reload: load, rename, remove };
}
