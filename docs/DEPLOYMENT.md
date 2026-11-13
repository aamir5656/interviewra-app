# Deployment guide (all free tiers)

Order matters: **LLM key -> database -> backend -> frontend -> CORS**. Plan for about 30 minutes.

| Piece | Service | Needs |
| --- | --- | --- |
| Database | [Neon](https://neon.tech) (or Supabase) | free account |
| Backend | [Render](https://render.com) web service | GitHub repo, free account |
| Frontend | [Vercel](https://vercel.com) | GitHub repo, free account |
| LLM | [Google AI Studio](https://aistudio.google.com/apikey) or [Groq](https://console.groq.com/keys) | free API key |

Push the repo to GitHub first (make sure `backend/alembic/versions/` contains your migration file and that no `.env` file is committed; `.gitignore` already blocks them).

## 1. Free LLM key

- **Gemini:** AI Studio -> "Get API key" -> create. Set `LLM_PROVIDER=gemini`, `LLM_API_KEY=<key>`, `LLM_MODEL=<a model name shown in AI Studio, e.g. a "flash" model>`.
- **Groq:** console -> API Keys -> create. Set `LLM_PROVIDER=groq`, `LLM_API_KEY=<key>`, `LLM_MODEL=<a model from the Groq models page that supports tool calling>`.

Free tiers have rate limits; if replies fail with "AI is busy", wait a minute. Keep the key only in Render's environment screen, never in the repo.

## 2. Database (Neon)

1. Create a project (region close to your Render region).
2. Copy the connection string (Dashboard -> Connect). Both `postgresql://...` and `postgres://...` are accepted; the app rewrites it for asyncpg and understands `sslmode=require`.
3. **Pooled vs direct:** the pooled host (contains `-pooler`) works too; the app switches off asyncpg's prepared-statement cache automatically for it. If you see `prepared statement ... does not exist`, use the direct connection string instead.

Supabase works the same way: use the connection string from Project Settings -> Database (the "session pooler" string is the safest choice on IPv4 hosts like Render).

## 3. Secret key

```bash
openssl rand -hex 32
# no openssl? python -c "import secrets; print(secrets.token_hex(32))"
```

The app refuses to start with `ENV=production` and a weak `SECRET_KEY` (shorter than 32 characters or starting with `change-me`). Render's blueprint can generate one for you (`generateValue: true`).

## 4. Backend on Render

**Option A, blueprint (fastest):** Render -> New + -> Blueprint -> select the repo. It reads `render.yaml`. Fill in `DATABASE_URL`, `CORS_ORIGINS` (leave a placeholder for now), `LLM_MODEL`, `LLM_API_KEY`.

**Option B, manual:** New + -> Web Service -> your repo, then:

| Setting | Value |
| --- | --- |
| Root Directory | `backend` |
| Runtime | Python 3 (or Docker, using `backend/Dockerfile`) |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'` |
| Health Check Path | `/health` |
| Plan | Free |

`--proxy-headers` matters: without it every visitor looks like the same proxy IP and shares one rate-limit bucket.

### Environment variables on Render

| Name | Value |
| --- | --- |
| `ENV` | `production` (turns on HSTS, hides `/docs`, enforces a strong secret) |
| `DATABASE_URL` | Neon / Supabase connection string |
| `SECRET_KEY` | output of `openssl rand -hex 32` |
| `CORS_ORIGINS` | your Vercel URL, e.g. `https://interviewra.vercel.app` (no trailing slash; separate several with commas) |
| `LLM_PROVIDER` | `gemini` or `groq` |
| `LLM_MODEL` | model name from your provider |
| `LLM_API_KEY` | key from step 1 |
| `LLM_TIMEOUT_SECONDS` | `60` (optional, default 30) |
| `ENABLE_PARALLEL_EVAL` | `false` (optional; `true` costs 4x the calls per report) |
| `CLEANUP_INTERVAL_HOURS` | `24`; `0` turns the automatic cleanup off |
| `GUEST_RETENTION_DAYS` | `30`: guests unseen this long are deleted with their data |
| `ABANDON_AFTER_DAYS` | `3`: unfinished interviews older than this are marked abandoned |
| `SESSION_RETENTION_DAYS` | `365`: registered users' interviews older than this are deleted (`0` = keep forever) |
| `REFRESH_GRACE_DAYS` | `7`: an expired login token can still be swapped for a new one this long |
| `MAX_UPLOAD_MB`, `MAX_AGENT_STEPS`, `HISTORY_WINDOW`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `GUEST_TOKEN_EXPIRE_DAYS`, `LIMIT_*` | optional, defaults are fine |

### Migrations in production

The start command above runs `alembic upgrade head` on every boot, so each deploy brings the schema up to date before serving traffic. To run it by hand instead (for example from your laptop):

```bash
cd backend
DATABASE_URL="postgresql://...neon..." alembic upgrade head      # Git Bash / Mac / Linux
# PowerShell:  $env:DATABASE_URL="postgresql://..."; alembic upgrade head
```

After changing a model locally: `alembic revision --autogenerate -m "describe change"`, read the generated file, commit it, push. Render applies it on the next deploy.

### Check it

```bash
curl https://<your-service>.onrender.com/health      # {"status":"ok"}
```

The first call after a sleep takes up to a minute. `/docs` is intentionally disabled in production.

## 5. Frontend on Vercel

1. Add New -> Project -> import the repo.
2. **Root Directory:** `frontend`. Framework preset: Next.js (auto-detected).
3. Environment variable: `NEXT_PUBLIC_API_URL` = `https://<your-service>.onrender.com` (the origin only, no `/api/v1`, no trailing slash).
4. Deploy. `NEXT_PUBLIC_*` values are baked in at build time, so after changing the variable you must **redeploy**.

## 6. Connect them (CORS)

Back in Render, set `CORS_ORIGINS` to the exact Vercel origin (for example `https://interviewra.vercel.app`) and let the service redeploy. If you use a custom domain, add it too: `https://interviewra.vercel.app,https://interviewra.example.com`. Vercel preview URLs are different origins, so previews will not be able to call the API unless you add them.

## 7. Keep the free backend awake (optional)

Render's free service sleeps after about 15 minutes idle. The UI already shows a "server is waking up" banner, but you can also ping `/health`:

- **UptimeRobot / cron-job.org:** an HTTP monitor on `https://<service>.onrender.com/health` every 10 minutes (no code needed).
- **GitHub Actions:** `.github/workflows/keep-awake.yml` is included. Add a repository variable `BACKEND_URL` (Settings -> Secrets and variables -> Actions -> Variables). Scheduled runs can be delayed by GitHub.

Free instances have a monthly hour budget, so pinging 24/7 may use it all; ping only around demos if you care.

## 8. Smoke test after deploying

1. Open the Vercel URL, click Start, finish a short interview, open the report.
2. Sign up from the user icon; your history should stay.
3. Open the browser dev tools -> Network: API calls go to the Render URL and none fail with CORS errors.
4. Render -> Logs shows JSON request lines with `status` codes.

## Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| Browser console: "blocked by CORS policy" | `CORS_ORIGINS` is not the exact Vercel origin (scheme, no trailing slash). Fix it and redeploy the backend. |
| "Can't reach the server" banner on every page | `NEXT_PUBLIC_API_URL` wrong or missing; fix and redeploy the frontend. Or the backend is still waking up. |
| Backend exits with "SECRET_KEY must be a strong random value" | Set `SECRET_KEY` to `openssl rand -hex 32` output. |
| `relation "users" does not exist` | Migrations did not run: check the start command, or run `alembic upgrade head` by hand. Make sure your migration file is committed. |
| 503 `llm_not_configured` | `LLM_PROVIDER`, `LLM_MODEL` or `LLM_API_KEY` missing on Render. |
| Replies say the AI is busy | Provider rate limit. Wait a minute, or switch provider. |
| Everyone gets 429 quickly | The proxy flags are missing from the start command (`--proxy-headers --forwarded-allow-ips='*'`). |
| `prepared statement "__asyncpg_stmt_..." does not exist` | Pooled Neon endpoint on an old build; redeploy this version or use the direct connection string. |
| Voice button says unsupported | Speech recognition only exists in Chrome and Edge, and needs HTTPS (Vercel provides it). |
