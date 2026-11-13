"use client";

import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import { AuthDialog } from "@/components/layout/AuthDialog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useGuest } from "@/hooks/useGuest";

/** Shown once to guests right after the report appears. Dismissible; never blocks reading the report. */
export function SavePrompt() {
  const { isGuest, loading } = useGuest();
  const [open, setOpen] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (loading || !isGuest || dismissed) return;
    const t = window.setTimeout(() => {
      // let the score animation play first; never pile on top of a dialog the person opened themselves
      if (document.querySelector('[role="dialog"]')) setDismissed(true);
      else setOpen(true);
    }, 1500);
    return () => window.clearTimeout(t);
  }, [loading, isGuest, dismissed]);

  function close() {
    setOpen(false);
    setDismissed(true);
  }

  return (
    <>
      <Dialog open={open && isGuest} onOpenChange={(o) => (o ? setOpen(true) : close())}>
        <DialogContent className="print:hidden">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Sparkles className="size-5 text-brand" aria-hidden /> Save your results
            </DialogTitle>
            <DialogDescription>Save your results and track your progress. Create a free account.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={close}>
              Maybe later
            </Button>
            <Button
              onClick={() => {
                close();
                setAuthOpen(true);
              }}
            >
              Create account
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <AuthDialog open={authOpen} onOpenChange={setAuthOpen} defaultTab="register" />
    </>
  );
}
