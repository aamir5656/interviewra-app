"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Check, Pencil, Plus, Trash2, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type KeyboardEvent } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useGuest } from "@/hooks/useGuest";
import { useSessions } from "@/hooks/useSessions";
import { toastError } from "@/lib/errors";
import { formatDate } from "@/lib/report";
import { cn } from "@/lib/utils";
import type { InterviewSession } from "@/types";

export function sessionHref(s: InterviewSession): string {
  return s.status === "completed" ? `/interview/${s.id}/report` : `/interview/${s.id}`;
}

/** ChatGPT-style list of past interviews. Used inside the desktop aside and the mobile Sheet. */
export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { items, loading, error, rename, remove } = useSessions();
  const { isGuest } = useGuest();
  const pathname = usePathname();
  const router = useRouter();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [deleting, setDeleting] = useState<InterviewSession | null>(null);
  const [busy, setBusy] = useState(false);

  function startEdit(s: InterviewSession) {
    setEditingId(s.id);
    setDraft(s.title);
  }

  async function saveEdit(s: InterviewSession) {
    const title = draft.trim();
    setEditingId(null);
    if (!title || title === s.title) return;
    try {
      await rename(s.id, title);
    } catch (err) {
      toastError(err);
    }
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>, s: InterviewSession) {
    if (e.key === "Enter") void saveEdit(s);
    if (e.key === "Escape") setEditingId(null);
  }

  async function confirmDelete() {
    if (!deleting) return;
    setBusy(true);
    try {
      await remove(deleting.id);
      if (pathname.startsWith(`/interview/${deleting.id}`)) router.push("/interview/new");
      setDeleting(null);
    } catch (err) {
      toastError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="p-3">
        <Link href="/interview/new" onClick={onNavigate} className={cn(buttonVariants({ variant: "outline" }), "w-full justify-start")}>
          <Plus aria-hidden /> New Interview
        </Link>
      </div>

      <nav aria-label="Past interviews" className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {loading ? (
          <div className="space-y-2 px-1">
            {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
          </div>
        ) : error && items.length === 0 ? (
          <p className="px-3 py-4 text-sm text-muted-foreground">Could not load your interviews.</p>
        ) : items.length === 0 ? (
          <p className="px-3 py-4 text-sm text-muted-foreground">No interviews yet. Start your first one.</p>
        ) : (
          <ul className="space-y-0.5">
            <AnimatePresence initial={false}>
              {items.map((s) => {
                const active = pathname.startsWith(`/interview/${s.id}`);
                return (
                  <motion.li
                    key={s.id}
                    layout="position"
                    initial={{ opacity: 0, x: -12 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -12 }}
                    transition={{ duration: 0.2 }}
                    className={cn("group relative rounded-lg", active ? "bg-accent" : "hover:bg-accent/60")}
                  >
                    {editingId === s.id ? (
                      <div className="flex items-center gap-1 p-2">
                        <Input
                          autoFocus
                          value={draft}
                          maxLength={120}
                          aria-label="Interview title"
                          onChange={(e) => setDraft(e.target.value)}
                          onKeyDown={(e) => onKey(e, s)}
                          className="h-8 px-2 text-sm"
                        />
                        <IconButton label="Save title" onClick={() => void saveEdit(s)}><Check className="size-4" /></IconButton>
                        <IconButton label="Cancel" onClick={() => setEditingId(null)}><X className="size-4" /></IconButton>
                      </div>
                    ) : (
                      <>
                        <Link
                          href={sessionHref(s)}
                          onClick={onNavigate}
                          aria-current={active ? "page" : undefined}
                          className="block rounded-lg px-3 py-2 pr-16 outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          {active && <span aria-hidden className="absolute top-2 bottom-2 left-0 w-0.5 rounded-full bg-primary" />}
                          <span className="block truncate text-sm font-medium">{s.title}</span>
                          <span className="block truncate text-xs text-muted-foreground">
                            {s.role_name} · {formatDate(s.created_at)}
                          </span>
                        </Link>
                        <div className="absolute top-1/2 right-1.5 flex -translate-y-1/2 gap-0.5 opacity-100 transition-opacity focus-within:opacity-100 lg:opacity-0 lg:group-hover:opacity-100">
                          <IconButton label={`Rename ${s.title}`} onClick={() => startEdit(s)}><Pencil className="size-3.5" /></IconButton>
                          <IconButton label={`Delete ${s.title}`} onClick={() => setDeleting(s)}><Trash2 className="size-3.5" /></IconButton>
                        </div>
                      </>
                    )}
                  </motion.li>
                );
              })}
            </AnimatePresence>
          </ul>
        )}
      </nav>

      {isGuest && (
        <p className="border-t border-border px-4 py-3 text-xs leading-relaxed text-muted-foreground">
          Sign up to keep your history forever. Guest interviews can be lost if you clear your browser.
        </p>
      )}

      <Dialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete this interview?</DialogTitle>
            <DialogDescription>
              &ldquo;{deleting?.title}&rdquo; and its report will be removed for good.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleting(null)}>Cancel</Button>
            <Button variant="destructive" disabled={busy} onClick={() => void confirmDelete()}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function IconButton({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-background hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      {children}
    </button>
  );
}
