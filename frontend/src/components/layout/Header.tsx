"use client";

import { History, LayoutDashboard, UserCircle2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Logo } from "@/components/icons/Logo";
import { AuthDialog } from "@/components/layout/AuthDialog";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { UserMenu } from "@/components/layout/UserMenu";
import { Button, buttonVariants } from "@/components/ui/button";
import { useGuest } from "@/hooks/useGuest";
import { SITE_NAME } from "@/lib/site";
import { cn } from "@/lib/utils";

export function Header() {
  const [authOpen, setAuthOpen] = useState(false);
  const { isGuest, loading } = useGuest();

  return (
    <header className="print:hidden sticky top-0 z-40 border-b border-border/70 bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between gap-2 px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2 rounded-md font-heading text-lg font-semibold tracking-tight">
          <Logo className="size-9 text-primary" />
          {SITE_NAME}
        </Link>

        <nav aria-label="Main" className="flex items-center gap-1">
          <Link href="/dashboard" className={cn(buttonVariants({ variant: "ghost", size: "default" }), "px-3")}>
            <LayoutDashboard aria-hidden />
            <span className="hidden sm:inline">Dashboard</span>
            <span className="sr-only sm:hidden">Dashboard</span>
          </Link>
          <Link href="/history" className={cn(buttonVariants({ variant: "ghost", size: "default" }), "px-3")}>
            <History aria-hidden />
            <span className="hidden sm:inline">History</span>
            <span className="sr-only sm:hidden">History</span>
          </Link>
          <ThemeToggle />
          {!loading && !isGuest ? (
            <UserMenu />
          ) : (
            <Button
              variant="ghost"
              size="icon"
              className="relative"
              aria-label={isGuest ? "Account (guest)" : "Account"}
              title="Account"
              onClick={() => setAuthOpen(true)}
            >
              <UserCircle2 className="size-6" />
              {!loading && isGuest && (
                <span aria-hidden className="absolute top-2 right-2 size-2 rounded-full bg-brand-2 ring-2 ring-background" />
              )}
            </Button>
          )}
        </nav>
      </div>
      <AuthDialog open={authOpen} onOpenChange={setAuthOpen} defaultTab="register" />
    </header>
  );
}
