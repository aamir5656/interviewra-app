"use client";

import { motion, useReducedMotion } from "framer-motion";

import { Logo } from "@/components/icons/Logo";
import { Markdown } from "@/components/chat/Markdown";
import { TypingIndicator } from "@/components/chat/TypingIndicator";
import { balanceMarkdown } from "@/lib/markdown";
import { cn } from "@/lib/utils";

interface MessageBubbleProps {
  role: "user" | "assistant";
  content: string;
  /** this bubble is the one being written right now */
  streaming?: boolean;
}

export function MessageBubble({ role, content, streaming = false }: MessageBubbleProps) {
  const reduce = useReducedMotion();
  const mine = role === "user";
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 420, damping: 32, mass: 0.8 }}
      className={cn("flex w-full gap-2.5", mine ? "justify-end" : "justify-start")}
    >
      {!mine && <Logo className="mt-1 size-7 shrink-0 text-primary" />}
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm sm:max-w-[75%]",
          mine
            ? "rounded-tr-sm bg-primary whitespace-pre-wrap break-words text-primary-foreground"
            : "rounded-tl-sm border border-border bg-card text-card-foreground",
        )}
      >
        {mine ? (
          content
        ) : (
          <>
            <p className="mb-0.5 text-xs font-medium text-muted-foreground">Alex, AI interviewer</p>
            {content === "" ? <TypingIndicator /> : <Markdown>{streaming ? balanceMarkdown(content) : content}</Markdown>}
          </>
        )}
      </div>
    </motion.div>
  );
}
