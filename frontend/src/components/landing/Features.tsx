"use client";

import { motion, useReducedMotion } from "framer-motion";
import { BarChart3, Brain, FileText, MessagesSquare, ShieldCheck, Target, type LucideIcon } from "lucide-react";

import { DURATION, EASE, VIEWPORT } from "@/components/landing/motion";

const FEATURES: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: MessagesSquare, title: "A real conversation", text: "One question at a time, with follow-ups that react to what you actually said." },
  { icon: Target, title: "Built for your level", text: "Intern to senior, technical, HR or behavioral. Difficulty is calibrated to you." },
  { icon: FileText, title: "Knows your resume", text: "Upload a resume and the questions get personal, based only on what is in it." },
  { icon: BarChart3, title: "A report you can act on", text: "Scores by category, feedback per question and a hint for a stronger answer." },
  { icon: Brain, title: "Remembers your progress", text: "With a free account it recalls your strengths and weak spots and tracks your trend." },
  { icon: ShieldCheck, title: "Free and private", text: "Start in one click as a guest. Your history stays yours and you can delete it." },
];

export function Features() {
  const reduce = useReducedMotion();
  return (
    <section id="features" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
      <div className="mx-auto mb-12 max-w-2xl text-center">
        <h2 className="text-3xl font-bold sm:text-4xl">Everything a good mock interview needs</h2>
        <p className="mt-3 text-muted-foreground">Practice that feels real, feedback that is specific.</p>
      </div>
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map(({ icon: Icon, title, text }, i) => (
          <motion.li
            key={title}
            initial={reduce ? false : { opacity: 0, y: 18 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={VIEWPORT}
            transition={{ duration: DURATION.base, ease: EASE, delay: reduce ? 0 : (i % 3) * 0.06 }}
            className="rounded-xl border border-border bg-card p-5 transition-colors duration-200 hover:border-brand/50"
          >
            <span className="mb-4 grid size-10 place-items-center rounded-lg bg-primary/12 text-brand">
              <Icon className="size-5" aria-hidden />
            </span>
            <h3 className="text-lg font-semibold">{title}</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{text}</p>
          </motion.li>
        ))}
      </ul>
    </section>
  );
}
