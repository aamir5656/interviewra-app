"use client";

import { Loader2 } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useGuest } from "@/hooks/useGuest";
import { ApiError, api } from "@/lib/api";
import type { ChangePasswordRequest, TokenResponse } from "@/types";

type Errors = Partial<Record<"current" | "next" | "confirm" | "form", string>>;

function validate(current: string, next: string, confirm: string): Errors {
  const e: Errors = {};
  if (!current) e.current = "Enter your current password.";
  if (next.length < 8) e.next = "Use at least 8 characters.";
  else if (new TextEncoder().encode(next).length > 72) e.next = "That password is too long (max 72 bytes).";
  else if (next === current) e.next = "Choose a password different from the current one.";
  if (confirm !== next) e.confirm = "The two passwords do not match.";
  return e;
}

/** Form to change the password. Mounted by UserMenu only while open, so its state resets on every open. */
export function ChangePasswordDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { setSession } = useGuest();
  const uid = useId();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);

  async function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    const found = validate(current, next, confirm);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    setBusy(true);
    try {
      const body: ChangePasswordRequest = { current_password: current, new_password: next };
      const auth = await api.post<TokenResponse>("/auth/change-password", body);
      setSession(auth); // the old token no longer works; keep this device signed in with the new one
      toast.success("Password changed.");
      onOpenChange(false);
    } catch (err) {
      if (err instanceof ApiError && err.code === "wrong_password") setErrors({ current: err.message });
      else setErrors({ form: err instanceof ApiError ? err.message : "Something went wrong. Please try again." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Change password</DialogTitle>
          <DialogDescription>You stay signed in here. Other devices will need to log in again.</DialogDescription>
        </DialogHeader>
        <form onSubmit={(e) => void onSubmit(e)} noValidate className="grid gap-4">
          <Field id={`${uid}-cur`} label="Current password" error={errors.current}>
            <Input id={`${uid}-cur`} type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} aria-invalid={!!errors.current} />
          </Field>
          <Field id={`${uid}-new`} label="New password" error={errors.next}>
            <Input id={`${uid}-new`} type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} aria-invalid={!!errors.next} />
          </Field>
          <Field id={`${uid}-conf`} label="Confirm new password" error={errors.confirm}>
            <Input id={`${uid}-conf`} type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} aria-invalid={!!errors.confirm} />
          </Field>
          {errors.form && <p role="alert" className="text-sm text-destructive">{errors.form}</p>}
          <Button type="submit" disabled={busy}>
            {busy && <Loader2 className="animate-spin" aria-hidden />} Change password
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Field({ id, label, error, children }: { id: string; label: string; error?: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
