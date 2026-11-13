"use client";

import { Loader2, UserCircle2 } from "lucide-react";
import { useEffect, useId, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { notifySessionsChanged } from "@/hooks/useSessions";
import { useGuest } from "@/hooks/useGuest";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { SessionList, TokenResponse } from "@/types";

export type AuthTab = "register" | "login";

interface AuthDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultTab?: AuthTab;
}

type Errors = Partial<Record<"name" | "email" | "password" | "form", string>>;

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function validate(tab: AuthTab, name: string, email: string, password: string): Errors {
  const e: Errors = {};
  if (tab === "register" && !name.trim()) e.name = "Enter your name.";
  if (!EMAIL_RE.test(email.trim())) e.email = "Enter a valid email address.";
  if (tab === "register" ? password.length < 8 : password.length === 0) {
    e.password = tab === "register" ? "Use at least 8 characters." : "Enter your password.";
  }
  return e;
}

export function AuthDialog({ open, onOpenChange, defaultTab = "register" }: AuthDialogProps) {
  const { user, isGuest, setSession } = useGuest();
  const uid = useId();
  const [tab, setTab] = useState<AuthTab>(defaultTab);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const [askMerge, setAskMerge] = useState(false);

  useEffect(() => {
    if (!open) return;
    const t = window.setTimeout(() => {
      setTab(defaultTab);
      setErrors({});
      setAskMerge(false);
      setPassword("");
    }, 0);
    return () => window.clearTimeout(t);
  }, [open, defaultTab]);

  function switchTab(next: AuthTab) {
    setTab(next);
    setErrors({});
    setAskMerge(false);
  }

  function done(auth: TokenResponse, message: string) {
    setSession(auth);
    notifySessionsChanged();
    toast.success(message);
    onOpenChange(false);
  }

  function fail(err: unknown) {
    const message = err instanceof ApiError ? err.message : "Something went wrong. Please try again.";
    if (err instanceof ApiError && err.code === "email_taken") setErrors({ email: message });
    else setErrors({ form: message });
  }

  async function login(merge: boolean) {
    setBusy(true);
    try {
      const auth = await api.post<TokenResponse>("/auth/login", { email: email.trim(), password, merge_guest: merge });
      done(auth, `Welcome back, ${auth.user.display_name}.`);
    } catch (err) {
      setAskMerge(false);
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    const found = validate(tab, name, email, password);
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    if (tab === "register") {
      setBusy(true);
      try {
        const auth = await api.post<TokenResponse>("/auth/register", {
          email: email.trim(),
          password,
          display_name: name.trim(),
        });
        done(auth, "Account created. Your interviews are saved.");
      } catch (err) {
        fail(err);
      } finally {
        setBusy(false);
      }
      return;
    }

    if (isGuest) {
      setBusy(true);
      try {
        const mine = await api.get<SessionList>("/interviews?limit=1");
        if (mine.total > 0) {
          setBusy(false);
          setAskMerge(true); // let the person decide before the guest account is replaced
          return;
        }
      } catch {
        /* cannot tell: just log in without merging */
      }
      setBusy(false);
    }
    await login(false);
  }

  if (!isGuest && user) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <UserCircle2 className="size-5 text-brand" aria-hidden /> Your account
            </DialogTitle>
            <DialogDescription>Signed in as {user.display_name}.</DialogDescription>
          </DialogHeader>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {askMerge ? (
          <>
            <DialogHeader>
              <DialogTitle>Merge your guest interviews?</DialogTitle>
              <DialogDescription>Merge your guest interviews into this account? Otherwise they stay on the guest account and will not appear after login.</DialogDescription>
            </DialogHeader>
            {errors.form && <p role="alert" className="text-sm text-destructive">{errors.form}</p>}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button variant="ghost" disabled={busy} onClick={() => void login(false)}>
                No, skip
              </Button>
              <Button disabled={busy} onClick={() => void login(true)}>
                {busy && <Loader2 className="animate-spin" aria-hidden />} Yes, merge
              </Button>
            </div>
          </>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>{tab === "register" ? "Create your free account" : "Welcome back"}</DialogTitle>
              <DialogDescription>
                {tab === "register"
                  ? "Keep your interview history and track your progress. Your guest interviews stay with you."
                  : "Log in to see your saved interviews."}
              </DialogDescription>
            </DialogHeader>

            <div role="tablist" aria-label="Account" className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1">
              {(["register", "login"] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  role="tab"
                  aria-selected={tab === t}
                  onClick={() => switchTab(t)}
                  className={cn(
                    "rounded-md py-1.5 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                    tab === t ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {t === "register" ? "Sign up" : "Log in"}
                </button>
              ))}
            </div>

            <form onSubmit={(e) => void onSubmit(e)} noValidate className="grid gap-4">
              {tab === "register" && (
                <Field id={`${uid}-name`} label="Name" error={errors.name}>
                  <Input id={`${uid}-name`} autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} aria-invalid={!!errors.name} />
                </Field>
              )}
              <Field id={`${uid}-email`} label="Email" error={errors.email}>
                <Input id={`${uid}-email`} type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} aria-invalid={!!errors.email} />
              </Field>
              <Field id={`${uid}-pw`} label="Password" error={errors.password}>
                <Input
                  id={`${uid}-pw`}
                  type="password"
                  autoComplete={tab === "register" ? "new-password" : "current-password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  aria-invalid={!!errors.password}
                />
              </Field>
              {errors.form && <p role="alert" className="text-sm text-destructive">{errors.form}</p>}
              <Button type="submit" disabled={busy}>
                {busy && <Loader2 className="animate-spin" aria-hidden />}
                {tab === "register" ? "Create account" : "Log in"}
              </Button>
            </form>
          </>
        )}
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
