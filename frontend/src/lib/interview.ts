import type { InterviewType, Level } from "@/types";

/** Limits mirror the backend schemas (InterviewCreate / AnswerCreate). */
export const LIMITS = { countMin: 3, countMax: 10, countDefault: 5, answerMax: 4000 } as const;
export const MINUTES_PER_QUESTION = 3;

export const LEVELS: { value: Level; label: string; hint: string }[] = [
  { value: "intern", label: "Intern", hint: "Fundamentals" },
  { value: "junior", label: "Junior", hint: "0-2 years" },
  { value: "mid", label: "Mid", hint: "2-5 years" },
  { value: "senior", label: "Senior", hint: "5+ years" },
];

export const TYPES: { value: InterviewType; label: string; hint: string }[] = [
  { value: "technical", label: "Technical", hint: "Concepts and problem solving" },
  { value: "hr", label: "HR", hint: "Motivation and expectations" },
  { value: "behavioral", label: "Behavioral", hint: "Real past situations (STAR)" },
  { value: "mixed", label: "Mixed", hint: "A bit of everything" },
];

/** The only roles the backend accepts (backend/app/roles.py). */
export const ROLES = [
  "Frontend Developer",
  "Backend Engineer",
  "Full-Stack Developer",
  "Data Analyst",
  "DevOps Engineer",
  "QA Engineer",
  "Product Manager",
] as const;

export const levelLabel = (v: string) => LEVELS.find((l) => l.value === v)?.label ?? v;
export const typeLabel = (v: string) => TYPES.find((t) => t.value === v)?.label ?? v;
