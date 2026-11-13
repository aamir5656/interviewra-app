"use client";

import { PanelLeft, PanelLeftClose, PanelLeftOpen, Plus } from "lucide-react";
import Link from "next/link";
import { useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";

import { Sidebar } from "@/components/layout/Sidebar";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { SIDEBAR_MAX, SIDEBAR_MIN, clampWidth, useSidebarPrefs } from "@/hooks/useSidebarPrefs";
import { cn } from "@/lib/utils";

const RAIL = 48;

/**
 * Page frame with the history sidebar. Desktop: hidden by default (a slim rail with a toggle),
 * opens to a column that can be resized by dragging its right edge. Mobile: a slide-in Sheet.
 */
export function SidebarShell({ children }: { children: ReactNode }) {
  const [sheetOpen, setSheetOpen] = useState(false);
  const { open, width, setOpen, setWidth } = useSidebarPrefs();
  const [dragWidth, setDragWidth] = useState<number | null>(null);
  const start = useRef<{ x: number; w: number } | null>(null);

  const current = dragWidth ?? width;
  const dragging = dragWidth !== null;

  function onDown(e: PointerEvent<HTMLDivElement>) {
    start.current = { x: e.clientX, w: width };
    e.currentTarget.setPointerCapture(e.pointerId);
    setDragWidth(width);
  }
  function onMove(e: PointerEvent<HTMLDivElement>) {
    if (start.current) setDragWidth(clampWidth(start.current.w + e.clientX - start.current.x));
  }
  function onUp() {
    if (start.current && dragWidth !== null) setWidth(dragWidth);
    start.current = null;
    setDragWidth(null);
  }
  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === "ArrowLeft") setWidth(width - 16);
    if (e.key === "ArrowRight") setWidth(width + 16);
  }

  return (
    <div className="lg:flex">
      <aside
        aria-label="Interview history"
        style={{ width: open ? current : RAIL }}
        className={cn(
          "sticky top-16 hidden h-[calc(100dvh-4rem)] shrink-0 border-r border-border lg:block print:hidden",
          !dragging && "transition-[width] duration-200",
        )}
      >
        {open ? (
          <div className="relative flex h-full flex-col">
            <div className="flex h-12 shrink-0 items-center justify-between px-4">
              <span className="font-heading text-sm font-semibold">Interviews</span>
              <RailButton label="Hide sidebar" onClick={() => setOpen(false)}>
                <PanelLeftClose className="size-4" />
              </RailButton>
            </div>
            <div className="min-h-0 flex-1">
              <Sidebar />
            </div>
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize sidebar"
              aria-valuemin={SIDEBAR_MIN}
              aria-valuemax={SIDEBAR_MAX}
              aria-valuenow={current}
              tabIndex={0}
              onPointerDown={onDown}
              onPointerMove={onMove}
              onPointerUp={onUp}
              onPointerCancel={onUp}
              onKeyDown={onKey}
              className={cn(
                "absolute inset-y-0 -right-1 z-10 w-2 cursor-col-resize touch-none outline-none transition-colors hover:bg-primary/40 focus-visible:bg-primary/40",
                dragging && "bg-primary/60",
              )}
            />
          </div>
        ) : (
          <div className="flex h-full flex-col items-center gap-1 pt-3">
            <RailButton label="Show interview history" onClick={() => setOpen(true)}>
              <PanelLeftOpen className="size-4" />
            </RailButton>
            <Link
              href="/interview/new"
              aria-label="New interview"
              title="New interview"
              className="flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              <Plus className="size-4" />
            </Link>
          </div>
        )}
      </aside>

      <div className="flex h-10 items-center border-b border-border px-3 lg:hidden print:hidden">
        <button
          type="button"
          onClick={() => setSheetOpen(true)}
          className="flex items-center gap-2 rounded-md px-2 py-1 text-sm text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <PanelLeft className="size-4" aria-hidden /> Interviews
        </button>
      </div>
      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent>
          <SheetTitle className="px-4 pt-4 font-heading text-lg font-semibold">Interviews</SheetTitle>
          <SheetDescription className="sr-only">Your past interviews</SheetDescription>
          <div className="min-h-0 flex-1">
            <Sidebar onNavigate={() => setSheetOpen(false)} />
          </div>
        </SheetContent>
      </Sheet>

      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

function RailButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      {children}
    </button>
  );
}
