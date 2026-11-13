# Security checklist

`[x]` = done and verified in this repo (with how), `[ ]` = yours to do or a known limit.

## Secrets and configuration

- [x] **No secrets committed.** `.gitignore` blocks `.env` and `.env.*` (except `.env.example`); a repo-wide search for key patterns found none. The example files hold placeholders only (`backend/.env.example`, `frontend/.env.example`).
- [x] **Strong secret enforced.** With `ENV=production` the app will not boot if `SECRET_KEY` is under 32 characters or starts with `change-me` (`tests/test_hardening.py`).
- [x] **API docs hidden in production** (`/docs` and `/openapi.json` are off when `ENV=production`).
- [x] **LLM key stays on the server.** The frontend only knows `NEXT_PUBLIC_API_URL`.
- [ ] Before going public: generate the production `SECRET_KEY` with `openssl rand -hex 32`, rotate any key that was ever pasted into a chat, screenshot or terminal log, and set a spending/quota cap on the LLM key.
- [ ] Turn on GitHub secret scanning (Settings -> Code security).

## Authentication and authorization

- [x] Passwords hashed with bcrypt; length bounded to 8-72 bytes, NUL bytes rejected (`test_register_validators_reject`).
- [x] JWT carries `sub`, `role`, `exp`; expired and tampered tokens are rejected (`tests/test_security.py`). The role is re-read from the database on every request.
- [x] **Ownership on every user-data query.** Interviews, messages, reports, resumes, memory and dashboard are all filtered by the signed-in user's id; another user's id answers 404, never 403, so ids cannot be probed (`test_other_user_gets_404_everywhere`, `test_resume_is_private_and_deletable`, `test_stats_only_count_own_reports`, `test_cannot_start_an_interview_with_someone_elses_resume`).
- [x] Guests cannot read the dashboard (403); admin-only routes use `require_role`.
- [x] Login does not reveal whether an email exists ("Invalid email or password"), and password checking runs even for unknown emails.
- [x] Signed-in users can change their password (current password required, rate limited). The token carries a password fingerprint, so a change invalidates every older token. Tokens are silently refreshed (`/auth/refresh`, only within `REFRESH_GRACE_DAYS` of expiry).
- [ ] Known limits: no email verification, no forgot-password email flow, no instant revocation (a stolen token works until it expires or the password changes). The token lives in `localStorage`, which an XSS bug could read; mitigated by rendering Markdown without raw HTML and by never using `dangerouslySetInnerHTML`.

## Input validation

- [x] Pydantic validators on every body (role name 2-80 chars, 3-10 questions, answers 1-4000 chars, titles 1-80, emails normalised); enum values restricted (`tests/test_hardening.py`, `tests/test_interviews.py`).
- [x] Uniform error shape without stack traces: `{"error": {"code", "message", "request_id"}}`.
- [x] JSON bodies are size-limited; the upload route has its own larger limit (`test_oversized_upload_is_cut_off_by_the_body_limit`, `test_body_too_large`).
- [x] Prompt-injection hygiene: candidate answers, resumes and transcripts are wrapped in delimiters, closing tags are neutralised, and prompts state they are data (`test_answer_cannot_break_out_of_delimiters`, `tests/test_prompts.py`).

## Uploads

- [x] Content type and **magic bytes** (`%PDF-`) must both say PDF; `MAX_UPLOAD_MB` size cap; page cap (15), extracted-text cap, encrypted and image-only PDFs rejected (`tests/test_resume.py`).
- [x] Extraction runs in a thread (`asyncio.to_thread`) so it cannot block the server; file names are sanitised; only the extracted text and summary are stored, never the file.
- [x] Per-role daily upload limit (`LIMIT_*_RESUMES_PER_DAY`); users can delete their resume.

## Abuse and cost control

- [x] Per-role daily limits for interviews, messages and resumes with `Retry-After` on 429 (`tests/test_limits.py`, `test_interview_limit_returns_429`, `test_message_limit_returns_429`).
- [x] Per-IP limits on every route, stricter for login/register and guest creation. Real client IPs need `--proxy-headers` behind Render (already in the start command).
- [x] Bounded agent loop (`MAX_AGENT_STEPS`) and bounded history window, so one request cannot trigger unlimited model calls.

## Transport and browser hardening

- [x] API responses carry `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, a locked-down `Content-Security-Policy`, `Cache-Control: no-store` on `/api/*`, and HSTS in production (`test_security_headers_and_request_id`).
- [x] The frontend sets `nosniff`, `X-Frame-Options: DENY`, a referrer policy and a permissions policy (`frontend/next.config.ts`; the microphone stays allowed for voice answers).
- [x] CORS allows only the origins in `CORS_ORIGINS`, only the needed headers, no credentials/cookies (`test_cors_allows_only_configured_origins`).
- [x] No cookies are used, so there is no CSRF surface.
- [ ] A strict CSP for the Next.js app is not set (Next injects inline scripts); add a nonce-based CSP if you need it.

## Operations

- [x] Request IDs on every response and log line; logs are JSON and never print secrets, passwords or resume text.
- [x] CI (`.github/workflows/ci.yml`) runs lint and the full test suite on every push.
- [ ] Neon free tier has no point-in-time restore guarantees; export the database if the data matters.
- [x] A background cleanup job (`services/cleanup.py`) deletes guests unseen for `GUEST_RETENTION_DAYS`, abandons stale interviews and drops old usage counters. On Render free the service sleeps, so it runs a minute after each wake-up and then every `CLEANUP_INTERVAL_HOURS`.
