## HANDOFF: Part 1: Backend foundation
Status: complete
Public interfaces: get_settings(); Base, engine, async_session_factory, get_db(); models User, Resume, InterviewSession, Message, Feedback, UserMemory, UsageCounter; AppError(code, message, status_code=400, headers=None); error_response(); register_error_handlers(app); request_id_of(request); setup_logging(); redact(); scrub_text(); main.API_PREFIX="/api/v1"
Known gaps: cleanup_loop placeholder; slowapi limiter not added; no auth/LLM/routers yet.

## RENAME NOTICE
Project renamed MockMate -> Interviewra. Contract changes: repo root `interviewra/`; frontend localStorage key is now `interviewra_token` (was `mockmate_token`). Everything else in the CONTRACT is unchanged.

## HANDOFF: Part 2: Guest identity, auth, limits
Status: complete (21 tests)
Files: app/core/security.py (hash_password, verify_password, create_access_token, decode_token); app/schemas.py (RegisterRequest, LoginRequest, UserOut, TokenResponse); app/dependencies.py (get_current_user, get_optional_user, require_role, DbSession, CurrentUser, OptionalUser); app/core/limits.py (check_and_increment(db, user, kind: "interview"|"message"), check_resume_limit, get_limit, seconds_until_utc_midnight); app/core/ratelimit.py (limiter, rate_limit_exceeded_handler); app/routers/auth.py (POST /auth/guest, /auth/register, /auth/login (merge_guest), GET /auth/me); tests conftest/test_auth/test_limits/test_security; pytest.ini (asyncio_mode=auto).
Decisions: guest-first; register with a guest token upgrades the same user row; login with merge_guest moves sessions+resumes then deletes the guest; role read from DB not token; per-role daily limits via atomic upsert on usage_counters (429 code rate_limited + Retry-After); per-IP slowapi limits (DEFAULT 60/minute, AUTH 10/minute, GUEST_CREATE 20/hour).
Test: cd backend && pytest -q

## HANDOFF: Part 3: LLM provider layer and prompts
Status: complete (57 tests total; only Gemini chat_json verified against the real API, tools/streaming/Groq tested with mocked HTTP)
Files: app/services/llm/{base,retry,http_provider,gemini,groq,__init__}.py; app/services/prompts.py (render(name, **vars), fence_safe); app/prompts/{interviewer,evaluator,summarizer,title,resume_summary}.md; tests/conftest.py (FakeProvider, tool_call, tool_response, use_fake_llm fixture); scripts/llm_check.py.
Interfaces: get_provider(), set_provider_override(p); LLMProvider.stream_chat(system, messages)->AsyncIterator[str], chat_json(system, messages, schema=None)->dict (AppError llm_bad_json 502), chat_with_tools(system, messages, tools)->LLMResponse(text, tool_calls, usage); ChatMessage(role, content, tool_calls, tool_call_id, name); ToolSpec; ToolCall(id, name, arguments, extra); BEGIN_TURN_TEXT="Begin.". Retry 3x on 429/5xx/timeout then AppError llm_unavailable 503; no key/model -> llm_not_configured 503.
Env: LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, LLM_TIMEOUT_SECONDS (user's working values: gemini, gemini-3.5-flash-lite, 60).

## HANDOFF: Part 4: Interview start, answer streaming, history
Status: complete (22 tests in tests/test_interviews.py)
Files: app/core/sse.py: sse_event(name, data), guarded_stream(events, on_abort), sse_response(events, on_abort, **kw); app/database.py: +SessionFactory, get_session_factory (independent sessions for streaming/background); app/schemas.py: +InterviewCreate, AnswerCreate, InterviewRename, MessageOut, SessionOut, SessionList, SessionDetail; app/services/conversation.py: build_messages(db, session, new_answer|None, *, wrap_up=False)->(system, messages), get_owned_session(db, user, id) (404 not_found), new_message(), wrap_answer(), CHAT_ROLES; app/routers/interview.py: POST /interviews, POST /interviews/{id}/answer; app/routers/history.py: GET /interviews?limit&offset, GET/PATCH/DELETE /interviews/{id}; app/prompts/turn_notes.md; services/prompts.py fence_safe also guards </candidate_answer>; main.py registers both routers; tests/conftest.py overrides get_session_factory; tests/helpers.py.
Public interfaces: SSE events: session {session_id} (first, start only), token {text}, done {message_id, ready_to_end}, error {code, message}. List response {items, total, limit, offset}. Detail = SessionOut + messages(user/assistant) + feedback(Report|null).
Env used: HISTORY_WINDOW, LIMIT_*_PER_DAY.
Decisions/deviations: added `session` SSE event (allowed). Answer checks ownership -> status (409 session_not_active) -> limit. Failed first question deletes the empty session; failed answer deletes the unanswered user message (quota stays used). Title generated in a background task right after the first question. Temporary counting: current_question_index +1 per assistant turn (follow-ups count); wrap_up when index_before >= question_count; ready_to_end when new index > question_count. Message/session created_at set explicitly in Python.
Test: cd backend && pytest -q tests/test_interviews.py
TODO Part 6/tools: replace temporary counting with end_interview tool; extend build_messages with rolling_summary + user memory; turn_notes.md says "no tools available" (remove when tools arrive).

## HANDOFF: Part 5: Evaluation and report
Status: complete (13 tests in tests/test_evaluator.py; 91 total)
Files: app/services/evaluator.py: build_transcript(messages), generate_report(role_name, level, interview_type, transcript)->Report, merge_reports(), fallback_report(), to_feedback(session_id, report), from_feedback(fb); app/schemas.py: +Report, CategoryScores, PerQuestion, clamp_score; app/services/memory.py: update_long_term_memory(user_id, session_id) stub; app/routers/interview.py: POST /interviews/{id}/end, GET /interviews/{id}/report; prompts: eval_merge.md (new), evaluator.md (+optional `focus` block); config/.env.example: ENABLE_PARALLEL_EVAL default now false.
Public interfaces: Report = contract report JSON + `is_fallback: bool`. /end is idempotent, evaluates only for status active, saves feedback + status completed + ended_at, schedules update_long_term_memory as a background task only on first completion. /report 404 code report_not_found.
Env used: ENABLE_PARALLEL_EVAL.
Decisions: feedback.tips JSON = {"improvement_tips", "recommended_topics", "is_fallback"}. Unparseable model output (after 1 retry) -> saved fallback report (scores 0, is_fallback true; dashboards must exclude is_fallback rows). Provider outage (llm_unavailable) -> HTTP 503, nothing saved, /end can be retried. Parallel mode: 3 perspectives via asyncio.gather (4 LLM calls with the merge); per_question merged by position.
Test: cd backend && pytest -q
TODO Part 6: real update_long_term_memory; rolling summary.

## HANDOFF: Part 6: Agent loop, tools, memory
Status: complete (109 tests total; 18 new in tests/test_agent.py)
Files: app/data/question_bank.json (28 questions: track, type, topic, difficulty, question); app/services/tools.py: ToolContext, tool_specs(wrap_up, registered), execute_tool(ctx, call)->dict, TOOL_LABELS, load_bank(); app/services/agent.py: run_agent_turn(provider, ctx, system, messages, tools, result: AgentResult, *, max_steps, wrap_up=False)->AsyncIterator[str] (SSE strings); app/services/memory.py: update_long_term_memory(user_id, session_id, factory=None), summarize_old_messages(session_id, factory=None, provider=None), compact_profile, merge_profile, load_profile, split_summary/join_summary; app/routers/memory.py: GET /memory -> {profile, updated_at}, DELETE /memory (204); app/services/conversation.py: build_messages now adds rolling summary + candidate_profile, +session_ready_to_end(db, session_id); app/routers/interview.py: start/answer now run the agent, /end passes factory to the memory task; routers/history.py + schemas.SessionDetail: +ready_to_end; prompts/turn_notes.md updated.
Public interfaces: SSE adds tool_event {name, label} (labels: Choosing the next topic / Looking up a question idea / Recalling your past sessions / Wrapping up your interview). done.ready_to_end = true after end_interview. New error: 409 interview_finished (answer after end_interview). GET /interviews/{id} has ready_to_end.
Env used: MAX_AGENT_STEPS, HISTORY_WINDOW.
Decisions: current_question_index and covered_topics are changed ONLY by get_next_topic (follow-ups do not count). Wrap-up turn (index >= question_count) offers only end_interview and the server ends the interview even if the model forgets the call. end_interview is recorded in the last assistant message's tool_calls (that is how ready_to_end survives a reload); role=tool messages are not stored. Final text of a turn comes from chat_with_tools and is chunked into token events (no second model call). Tools run in parallel (gather), DB-touching ones serialise through ctx.lock. A failed turn restores covered_topics/index and deletes the unanswered user message. rolling_summary is stored as "[[summarized:N]]\n<text>" (N = messages folded in); summarised only when >=4 new messages left the window. Long-term memory = deterministic merge (no LLM): strengths, weak_topics (=recommended_topics), score_trend(last 10), resume_summary, session_ids; skipped for guests and fallback reports; candidate_profile = {resume_summary (any user), past_sessions (registered only)}. Guests do not get the get_user_memory tool.
Test: cd backend && pytest -q tests/test_agent.py
TODO: resume upload (fills Resume.summary) and dashboard/usage endpoints are still open.

## HANDOFF: Part 7: Frontend foundation and landing page
Status: complete (tsc, eslint and `next build` clean; checked in a real browser against the backend: guest token created and valid on /auth/me, dark/light toggle, token reused after reload, no horizontal scroll at 390px)
Stack as installed: Next 16.4 (App Router, src dir), React 19.3, Tailwind 4 (CSS-first: tokens in src/styles/globals.css, `@plugin "@tailwindcss/typography"`, no tailwind.config), framer-motion, lucide-react, sonner, next-themes, recharts, react-markdown, remark-gfm, canvas-confetti. shadcn is hand-written in the shadcn style (only components/ui/button.tsx and dialog.tsx exist so far); components.json is configured (css: src/styles/globals.css).
Files: src/styles/globals.css (tokens --bg --surface --border --text --muted --accent --accent-2 (+--on-accent), mapped to shadcn names; dark class = Midnight Lime default, light = Warm Paper); src/app/layout.tsx (Space Grotesk + Inter via next/font, Providers, Header, ServerStatusBanner, skip link); src/app/page.tsx + components/landing/{Hero,Features,HowItWorks,Footer,ChatPreview,AnimatedBackground,motion}.tsx; placeholder pages app/history/page.tsx and app/interview/new/page.tsx (ComingSoon); components/layout/{Header,AuthDialog (placeholder),ThemeToggle,ServerStatusBanner,ComingSoon}.tsx; components/providers/{Providers,GuestProvider}.tsx; components/icons/GithubIcon.tsx; lib/{api,sse,site,utils}.ts; hooks/{useGuest,useServerStatus}.ts; types/index.ts (mirrors backend schemas incl. Report, SessionDetail.ready_to_end, SSE event types).
Public interfaces: lib/api.ts: TOKEN_KEY="interviewra_token", API_BASE, getToken/setToken/clearToken, authHeaders(), class ApiError(status, code, message, requestId?, retryAfter?) with isRateLimited/isUnauthorized/isNetworkError (status 0 = unreachable), api.get/post/patch/delete<T>(path, ...) (path WITHOUT /api/v1), toApiError(res), isServerWaking()/subscribeServerStatus(). lib/sse.ts: streamSSE(path, body, handlers: {onSession,onToken,onToolEvent,onDone,onError}, signal?) (POST + Bearer token, throws ApiError for non-2xx), parseSSEBuffer. hooks/useGuest(): {user, isGuest, loading, error, refresh(), setSession(TokenResponse), logout()}. hooks/useServerWaking(): boolean. components: <Header/>, <AuthDialog open onOpenChange/> (placeholder, real one in the auth part), <ThemeToggle/>.
Env: NEXT_PUBLIC_API_URL (backend ORIGIN, e.g. http://localhost:8000; "/api/v1" is added by lib/api.ts).
Decisions: localStorage key is interviewra_token (rename notice). Footer has no dynamic year (Next 16 rejects new Date() in a prerendered server component). "Server is waking up" banner appears when a request runs longer than 4 s. Guest bootstrap is deduplicated (React strict mode). GITHUB_URL in lib/site.ts is a placeholder.
Run: cd frontend && npm install && cp .env.example .env.local && npm run dev (backend must run on :8000 with CORS_ORIGINS including http://localhost:3000). Missing shadcn components for later parts: npx shadcn@latest add dropdown-menu tabs tooltip select switch skeleton input label textarea sheet (do NOT re-add button/dialog).
TODO: /interview/new, /history and AuthDialog are placeholders (next frontend parts); set GITHUB_URL.

## HANDOFF: Part 8: Interview setup and live chat UI
Status: complete (tsc, eslint, `next build` clean; checked in a real browser against the backend with a scripted LLM: setup validation, start -> navigation while the first reply streams, tool hint, markdown (bold/lists/italics, no raw asterisks), progress "Question X of N", answers, "Interview complete", Get my report -> report page, reload of a finished interview, 429 toast with reset time, no horizontal scroll at 390px)
Files: app/interview/new/page.tsx (renders SetupForm); app/interview/[id]/page.tsx + report/page.tsx (params read inside <Suspense>, required by cacheComponents); components/interview/{SetupForm,InterviewRoom,ReportPlaceholder}.tsx; components/chat/{ChatWindow,MessageBubble,Markdown,Composer,ToolHint,TypingIndicator}.tsx; components/ui/{input,label,skeleton,textarea}.tsx (shadcn style, hand-written); hooks/useInterview.ts; lib/{interview,errors,markdown}.ts; styles/globals.css (+ prose theme variables, typing animation).
Public interfaces: hooks/useInterview({abortOnUnmount?: "always"|"until-session"}) -> {sessionId, messages: ChatItem[], streaming, toolHint, readyToEnd, failure, start(config: InterviewCreate): Promise<boolean>, sendAnswer(text): Promise<boolean>, hydrate(detail: SessionDetail), abort()}. The chat state lives in a module-level store (not in a component), so the stream survives the router.replace from /interview/new to /interview/[id] that happens on the `session` event. lib/interview.ts: LIMITS, LEVELS, TYPES, ROLE_SUGGESTIONS, levelLabel(), typeLabel(). lib/errors.ts: toastError(err) (friendly texts; 429 -> "Daily limit reached" + reset time from Retry-After), formatRetryAfter(seconds), friendlyMessage(code, message). components/chat/Markdown({children}) = react-markdown + remark-gfm in a themed prose container; MessageBubble({role, content, streaming}); Composer({onSend, disabled}).
Behaviour: a failed turn (error event, 429, 409, dropped connection) removes the optimistic user bubble and puts nothing on screen, because the backend also deletes the unanswered message; the composer text can be re-sent. After every reply the room re-fetches GET /interviews/{id} to refresh "Question X of N" and ready_to_end. "Get my report" calls POST /interviews/{id}/end (can take up to a minute) and navigates to /interview/{id}/report. A completed interview shows "View my report" instead of the composer.
Env: NEXT_PUBLIC_API_URL.
Decisions: level/type use radio cards and the question count a range slider (no shadcn select needed). "Upload resume" and "Per-question timer" are disabled placeholders (Part 10). Report page is a minimal placeholder (score + summary) until Part 9.
Shadcn components still to add for later parts: npx shadcn@latest add dropdown-menu tabs tooltip select switch sheet (input, label, skeleton, textarea now exist).
Test: backend on :8000 (CORS_ORIGINS includes http://localhost:3000, LLM_* set), cd frontend && npm run dev, open /interview/new.
TODO: real report UI (Part 9), AuthDialog, history page, resume upload, timer.

## HANDOFF: Part 9: Report, history sidebar, auth UI
Status: complete (evaluator scoring also made a little stricter in backend/app/prompts/evaluator.md).
Files created/changed (frontend/src unless noted):
- components/report/{ScoreRing,ScoreCard,CategoryBars,RadarChartCard,QuestionBreakdown,InsightLists,ReportView}.tsx: animated report (count-up ring, bars, Recharts radar, accordion, lists, topic chips, confetti >= 80, print button)
- lib/report.ts: scoreTone, CATEGORY_LABELS, formatDate
- components/layout/{AuthDialog,SavePrompt,UserMenu,Sidebar,SidebarShell}.tsx; Header.tsx (UserMenu for registered users)
- components/ui/sheet.tsx: left drawer on the dialog primitive (no new npm deps)
- components/history/HistoryList.tsx, app/history/{layout,page}.tsx, app/interview/layout.tsx (sidebar frame, inside Suspense)
- app/interview/[id]/report/page.tsx now renders ReportView (ReportPlaceholder deleted)
- hooks/useSessions.ts: useSessions() {items, loading, error, reload, rename, remove}; notifySessionsChanged()
- hooks/useInterview.ts: calls notifySessionsChanged() on `done`; InterviewRoom height adjusted for the mobile bar; styles/globals.css: @media print rules
Public interfaces: <AuthDialog open onOpenChange defaultTab?="register"|"login"/>, <SavePrompt/>, <Sidebar onNavigate?/>, <SidebarShell/>, <ReportView id/>
Env vars: none new.
Decisions: no shadcn dropdown/tabs/sheet installed; hand-written (tabs and menu are simple, sheet uses react-dialog). Login asks about merging only if the guest has interviews.
Run/test: npm run dev; guest interview -> report -> sign up -> log out -> guest interview -> log in with merge.
Known gaps: dashboard/progress page, resume upload UI (Parts 10-11).

Part 9 update: desktop sidebar is hidden by default (48px rail), opens/closes with a toggle, drag the right edge (or arrow keys) to resize 220-440px; state in localStorage `interviewra_sidebar` (hooks/useSidebarPrefs.ts). useSessions clears its list when the signed-in user changes.

## HANDOFF: Part 10: Extras: resume, voice, timer, dashboard
Status: complete. The backend endpoints (POST/GET/DELETE /resume, resume_id in session creation, GET /dashboard/stats) already existed from earlier parts; this part added their tests and all the frontend.
Files created/changed:
- backend/tests/{pdfs.py,test_resume.py,test_dashboard.py}: make_pdf() helper; 8 resume tests, 4 dashboard tests (12 total, all pass)
- frontend/src/lib/resume.ts: validateResumeFile, uploadResume (XHR with progress), getResume, deleteResume
- components/interview/ResumeUpload.tsx: drag and drop, validation, progress, polling until the summary is ready, remove, privacy note; SetupForm.tsx uses it and has the timer switch
- hooks/useTimerPref.ts (localStorage `interviewra_timer`), components/chat/QuestionTimer.tsx, InterviewRoom.tsx shows it
- hooks/useSpeech.ts, components/chat/VoiceButton.tsx (+Waveform), Composer.tsx: mic, live preview, fallback message
- components/dashboard/{DashboardView,TrendChart}.tsx, app/dashboard/page.tsx, Header.tsx (Dashboard link), RadarChartCard.tsx (title prop), UserMenu.tsx ("Clear my memory"), types/index.ts, styles/globals.css (wave keyframes)
Public interfaces: <ResumeUpload onChange(resumeId|null, busy)/>, useSpeech({onFinal,lang}), <QuestionTimer resetKey running seconds onHide/>, <DashboardView/>
Env vars: MAX_UPLOAD_MB, LIMIT_*_RESUMES_PER_DAY (existing).
Decisions: timer is a global preference (3 min per question, amber at 30 s, never blocks); guests get a dashboard teaser (API returns 403 for guests); resume summary failures show a note and the interview runs unpersonalised.
Run/test: cd backend && python -m pytest tests/test_resume.py tests/test_dashboard.py -q; frontend: npm run dev.
Known gaps: voice needs Chrome/Edge (Firefox has no SpeechRecognition); dashboard "weak spots" group the evaluator's weakness sentences, not fixed topics.

## HANDOFF: Part 11: Tests, deployment, README
Status: complete (Docker image build and the frontend header response were not run in the sandbox; tsc/eslint/ruff and all 149 pytest tests pass)
Files created/changed:
- backend/tests/test_hardening.py: 28 tests (headers, CORS, upload cap, prod secret, Neon URL, validators, ownership, login merge)
- backend/ruff.toml: lint config
- backend/app/database.py: disables asyncpg statement caches when the URL contains "-pooler" (Neon PgBouncer)
- backend/Dockerfile, backend/.dockerignore: non-root image, healthcheck, runs migrations then uvicorn
- render.yaml: Render blueprint (start command, /health, env vars)
- .github/workflows/ci.yml: ruff + alembic + pytest; npm lint + tsc + build
- .github/workflows/keep-awake.yml: optional /health ping (repo variable BACKEND_URL)
- frontend/next.config.ts: security headers
- frontend/README.md: pointer to root README
- README.md, docs/DEPLOYMENT.md, docs/SECURITY_CHECKLIST.md, docs/demo-placeholder.svg
Public interfaces: none new
Env vars: TEST_DATABASE_URL (tests only); BACKEND_URL (GitHub repo variable, optional)
Decisions: start command runs `alembic upgrade head` on every boot; CORS_ORIGINS must be the exact Vercel origin
How to run: cd backend && alembic upgrade head && ruff check . && python -m pytest -q
Known gaps: guests and old sessions never purged (cleanup_loop placeholder); no email verification, password reset or token refresh; no CSP on the frontend; voice needs Chrome/Edge; GITHUB_URL in src/lib/site.ts is a placeholder; commit your alembic/versions migration (CI needs it); replace the demo GIF placeholder

## HANDOFF: Part 11 add-on: cleanup, token refresh, change password
Status: complete (163 backend tests pass; tsc + eslint clean)
Files created/changed:
- backend/app/services/cleanup.py: `purge_stale(db, now=None) -> dict`, `cleanup_loop()` (first run 60 s after start, then every CLEANUP_INTERVAL_HOURS)
- backend/app/main.py: starts cleanup_loop in lifespan when CLEANUP_INTERVAL_HOURS > 0
- backend/app/core/security.py: `password_version()`, `create_access_token(user_id, role, password_hash=None)` adds claim `pv`, `decode_token(token, leeway_seconds=0)`
- backend/app/dependencies.py: pv check in `_load_user`; `user_from_token(token, db, leeway_seconds)`
- backend/app/routers/auth.py: `POST /auth/refresh`, `POST /auth/change-password`
- backend/app/schemas.py: `ChangePasswordRequest`; backend/app/config.py: new settings
- backend/tests/test_account.py: 14 tests; backend/.env.example
- frontend/src/lib/api.ts (`refreshToken`, `canRefresh`, retry once on `token_expired`), lib/sse.ts (same for streams), types/index.ts, components/layout/ChangePasswordDialog.tsx, components/layout/UserMenu.tsx ("Change password" item)
- README.md, docs/DEPLOYMENT.md, docs/SECURITY_CHECKLIST.md
Public interfaces: POST /api/v1/auth/refresh (Bearer, expired up to REFRESH_GRACE_DAYS ok) -> TokenResponse; POST /api/v1/auth/change-password {current_password, new_password} -> TokenResponse (400 wrong_password / same_password, 403 for guests)
Env vars added: REFRESH_GRACE_DAYS=7, CLEANUP_INTERVAL_HOURS=24, GUEST_RETENTION_DAYS=30, ABANDON_AFTER_DAYS=3, SESSION_RETENTION_DAYS=365 (0 = keep)
Decisions: JWT gets extra claim `pv` (no DB migration needed); tokens without `pv` stay valid; no schema change
Known gaps: no email verification or forgot-password email; no instant revocation; dashboard and frontend not browser-tested for the refresh path

## Current status
Status: complete. 462 tests pass against a local PostgreSQL (about 30 seconds); ruff is clean; `alembic check` reports no drift. Remaining manual steps before going public: add the live URL and a real demo GIF to README.md, set `GITHUB_URL` in `frontend/src/lib/site.ts`, deploy following docs/DEPLOYMENT.md.
