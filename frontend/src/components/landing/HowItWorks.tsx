"use client";

import { motion, useReducedMotion } from "framer-motion";

import { DURATION, EASE, VIEWPORT } from "@/components/landing/motion";

const STEPS = [
  { title: "Choose your interview", text: "Pick a role, your level and the type. It takes ten seconds and needs no account." },
  { title: "Talk with Alex", text: "Answer one question at a time. Alex follows up, gives a hint if you are stuck and wraps up on time." },
  { title: "Read your report", text: "Get an overall score, category scores, feedback per question and topics to study next." },
  { title: "Improve and repeat", text: "Create a free account to keep your history and see your progress over time." },
];

export function HowItWorks() {
  const reduce = useReducedMotion();
  return (
    <section id="how-it-works" className="scroll-mt-20 border-y border-border bg-card/40 px-4 py-20 sm:px-6">
      <div className="mx-auto max-w-4xl">
        <h2 className="mb-12 text-center text-3xl font-bold sm:text-4xl">How it works</h2>
        <ol className="relative space-y-8 before:absolute before:top-2 before:bottom-2 before:left-5 before:w-px before:bg-border">
          {STEPS.map((s, i) => (
            <motion.li
              key={s.title}
              initial={reduce ? false : { opacity: 0, x: -16 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={VIEWPORT}
              transition={{ duration: DURATION.base, ease: EASE }}
              className="relative flex gap-5"
            >
              <span className="relative z-10 grid size-10 shrink-0 place-items-center rounded-full border border-brand/60 bg-background font-heading font-semibold text-brand">
                {i + 1}
              </span>
              <div className="pt-1.5">
                <h3 className="text-lg font-semibold">{s.title}</h3>
                <p className="mt-1 text-muted-foreground">{s.text}</p>
              </div>
            </motion.li>
          ))}
        </ol>
      </div>
    </section>
  );
}
