// Types mirror the backend schemas (backend/app/schemas.py). Keep names and fields in sync.

export type Role = "guest" | "user" | "admin";
export type Level = "intern" | "junior" | "mid" | "senior";
export type InterviewType = "technical" | "hr" | "behavioral" | "mixed";
export type SessionStatus = "active" | "completed" | "abandoned";
export type MessageRole = "system" | "user" | "assistant" | "tool";

export interface User {
  id: string;
  email: string | null;
  display_name: string;
  role: Role;
  is_guest: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  user: User;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  display_name: string;
}

export interface LoginRequest {
  email: string;
  password: string;
  merge_guest?: boolean;
}

/** Every backend error: { "error": { code, message, request_id } } */
export interface ApiErrorBody {
  error: { code: string; message: string; request_id: string };
}

export interface InterviewCreate {
  role_name: string;
  level: Level;
  interview_type: InterviewType;
  question_count?: number;
  resume_id?: string | null;
}

export interface InterviewSession {
  id: string;
  title: string;
  role_name: string;
  level: Level;
  interview_type: InterviewType;
  question_count: number;
  current_question_index: number;
  status: SessionStatus;
  created_at: string;
  ended_at: string | null;
}

export interface SessionList {
  items: InterviewSession[];
  total: number;
  limit: number;
  offset: number;
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  created_at: string;
}

export interface CategoryScores {
  technical_accuracy: number;
  communication: number;
  depth: number;
  problem_solving: number;
}

export interface PerQuestion {
  question: string;
  answer_summary: string;
  score: number;
  feedback: string;
  better_answer_hint: string;
  critical_mistake?: boolean;
  needed_prompting?: boolean;
  mistakes?: string[];
}

export interface Report {
  overall_score: number;
  category_scores: CategoryScores;
  summary: string;
  strengths: string[];
  weaknesses: string[];
  per_question: PerQuestion[];
  improvement_tips: string[];
  recommended_topics: string[];
  /** true when the AI report could not be produced (show a gentle note) */
  is_fallback: boolean;
  /** label chosen by the server from the score and the critical flag */
  verdict?: string;
  has_critical?: boolean;
}

export interface SessionDetail extends InterviewSession {
  messages: Message[];
  feedback: Report | null;
  ready_to_end: boolean;
}

export interface MemoryOut {
  profile: Record<string, unknown>;
  updated_at: string | null;
}

// ---- SSE events: `event: <name>\ndata: <json>\n\n` ----
export interface SessionEvent { session_id: string }
export interface TokenEvent { text: string }
export interface ToolEvent { name: string; label: string }
export interface DoneEvent { message_id: string; ready_to_end: boolean }
export interface StreamErrorEvent { code: string; message: string }

// ---- Part 10: resume + dashboard ----
export interface ResumeOut {
  resume_id: string;
  filename: string;
  pages: number | null;
  /** false while the summary is still being written */
  ready: boolean;
  /** true when no summary could be made (the interview still works, just not personalised) */
  failed: boolean;
}

export interface TrendPoint { date: string; score: number }
export interface WeakTopic { topic: string; count: number }
export interface DashboardStats {
  interview_count: number;
  average_score: number | null;
  score_trend: TrendPoint[];
  category_averages: Partial<CategoryScores>;
  top_weak_topics: WeakTopic[];
}
