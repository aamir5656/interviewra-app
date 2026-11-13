"use client";

import { Brain, KeyRound, LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ChangePasswordDialog } from "@/components/layout/ChangePasswordDialog";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useGuest } from "@/hooks/useGuest";
import { notifySessionsChanged } from "@/hooks/useSessions";
import { api } from "@/lib/api";
import { toastError } from "@/lib/errors";

/** Avatar button + small menu for registered users: log out and clear long-term memory. */
export function UserMenu() {
  const { user, logout } = useGuest();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [changePw, setChangePw] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!user) return null;
  const initial = (user.display_name.trim()[0] ?? "?").toUpperCase();

  async function clearMemory() {
    setBusy(true);
    try {
      await api.delete("/memory");
      toast.success("Memory cleared.");
      setConfirmClear(false);
    } catch (err) {
      toastError(err);
    } finally {
      setBusy(false);
    }
  }

  async function onLogout() {
    setOpen(false);
    await logout();
    notifySessionsChanged();
    router.push("/");
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label="Account menu"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex size-9 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        {initial}
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-50 mt-2 w-60 rounded-xl border border-border bg-card p-1.5 shadow-xl">
          <div className="px-3 py-2">
            <p className="truncate text-sm font-medium">{user.display_name}</p>
            {user.email && <p className="truncate text-xs text-muted-foreground">{user.email}</p>}
          </div>
          <div className="my-1 h-px bg-border" />
          <MenuItem icon={<Brain className="size-4" />} onClick={() => { setOpen(false); setConfirmClear(true); }}>
            Clear my memory
          </MenuItem>
          <MenuItem icon={<KeyRound className="size-4" />} onClick={() => { setOpen(false); setChangePw(true); }}>
            Change password
          </MenuItem>
          <MenuItem icon={<LogOut className="size-4" />} onClick={() => void onLogout()}>
            Log out
          </MenuItem>
        </div>
      )}
      {changePw && <ChangePasswordDialog open onOpenChange={setChangePw} />}
      <Dialog open={confirmClear} onOpenChange={setConfirmClear}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Clear my memory?</DialogTitle>
            <DialogDescription>Alex will forget what he learned about you from past interviews. Your interviews and reports stay.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmClear(false)}>Cancel</Button>
            <Button variant="destructive" disabled={busy} onClick={() => void clearMemory()}>Clear memory</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function MenuItem({ icon, onClick, children }: { icon: React.ReactNode; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
    >
      {icon}
      {children}
    </button>
  );
}
