"use client";

import { motion, useReducedMotion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { AnimatedBackground } from "@/components/landing/AnimatedBackground";
import { ChatPreview } from "@/components/landing/ChatPreview";
import { DURATION, EASE } from "@/components/landing/motion";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const WORDS: { text: string; accent?: boolean }[] = [
  { text: "Practice" }, { text: "the" }, { text: "interview" }, { text: "before" }, { text: "it" }, { text: "counts." },
  { text: "Get" }, { text: "honest", accent: true }, { text: "feedback", accent: true }, { text: "in" }, { text: "minutes." },
];

export function Hero() {
  const reduce = useReducedMotion();
  const fade = (delay: number) => ({
    initial: reduce ? false : { opacity: 0, y: 14 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: DURATION.base, ease: EASE, delay: reduce ? 0 : delay },
  });

  return (
    <section className="relative isolate px-4 pt-16 pb-20 sm:px-6 sm:pt-24 sm:pb-28">
      <AnimatedBackground />
      <div className="mx-auto max-w-4xl text-center">
        <motion.p
          {...fade(0)}
          className="mx-auto mb-5 inline-flex items-center gap-2 rounded-full border border-border bg-card/80 px-3 py-1 text-xs font-medium text-muted-foreground"
        >
          <span className="size-1.5 rounded-full bg-brand-2" aria-hidden /> Free · No signup · AI interviewer
        </motion.p>

        <h1 className="text-4xl leading-[1.08] font-bold sm:text-6xl">
          {WORDS.map((w, i) => (
            <motion.span
              key={i}
              initial={reduce ? false : { opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: DURATION.base, ease: EASE, delay: reduce ? 0 : 0.05 * i }}
              className={cn("mr-[0.25em] inline-block", w.accent && "text-brand")}
            >
              {w.text}
            </motion.span>
          ))}
        </h1>

        <motion.p {...fade(0.55)} className="mx-auto mt-6 max-w-2xl text-base text-muted-foreground sm:text-lg">
          Interviewra is an AI interviewer that asks one question at a time, follows up on your answers and then
          scores you with specific, level-aware feedback.
        </motion.p>

        <motion.div {...fade(0.7)} className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Link href="/interview/new" className={cn(buttonVariants({ size: "lg" }), "group w-full sm:w-auto")}>
            Start Free Mock Interview
            <ArrowRight className="transition-transform duration-200 group-hover:translate-x-0.5" aria-hidden />
          </Link>
          <a href="#how-it-works" className={cn(buttonVariants({ variant: "outline", size: "lg" }), "w-full sm:w-auto")}>
            See how it works
          </a>
        </motion.div>
      </div>

      <div className="mt-14 sm:mt-20">
        <ChatPreview />
      </div>
    </section>
  );
}
