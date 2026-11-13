"use client";

import { useEffect, useRef } from "react";

import { MessageBubble } from "@/components/chat/MessageBubble";
import { ToolHint } from "@/components/chat/ToolHint";
import { Skeleton } from "@/components/ui/skeleton";
import type { ChatItem } from "@/hooks/useInterview";

interface ChatWindowProps {
  messages: ChatItem[];
  streaming: boolean;
  toolHint: string | null;
  loading?: boolean;
}

const NEAR_BOTTOM_PX = 120;

export function ChatWindow({ messages, streaming, toolHint, loading = false }: ChatWindowProps) {
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true); // follow new text only while the user is near the bottom
  const lastCount = useRef(0);

  useEffect(() => {
    const el = scroller.current;
    if (!el || !stick.current) return;
    const added = messages.length !== lastCount.current;
    lastCount.current = messages.length;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (added && !reduce) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    else el.scrollTop = el.scrollHeight; // token updates: jump, so smooth scrolling never lags behind the text
  }, [messages, toolHint]);

  return (
    <div
      ref={scroller}
      onScroll={(e) => {
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
      }}
      role="log"
      aria-live="polite"
      aria-busy={streaming}
      aria-label="Interview conversation"
      className="flex-1 overflow-y-auto overscroll-contain px-4 py-5 sm:px-6"
    >
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
        {loading ? (
          <>
            <Skeleton className="h-20 w-3/4 rounded-2xl" />
            <Skeleton className="ml-auto h-12 w-1/2 rounded-2xl" />
            <Skeleton className="h-24 w-4/5 rounded-2xl" />
          </>
        ) : (
          messages.map((m, i) => (
            <MessageBubble key={m.id} role={m.role} content={m.content} streaming={streaming && i === messages.length - 1} />
          ))
        )}
        <ToolHint label={toolHint} />
      </div>
    </div>
  );
}
