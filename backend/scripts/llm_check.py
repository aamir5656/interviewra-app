"""Real-API diagnostic. Run from the backend folder:  python scripts/llm_check.py [model1 model2 ...]
Without arguments it tests LLM_MODEL from .env; with arguments it times each model.
Prints reachability, usable model names, and one timed test call. Never prints your key."""
import asyncio
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings  # noqa: E402

TEST_TIMEOUT = 90.0


async def timed(client: httpx.AsyncClient, label: str, method: str, url: str, **kw) -> httpx.Response | None:
    start = time.perf_counter()
    try:
        resp = await client.request(method, url, **kw)
    except httpx.TimeoutException:
        print(f"[{label}] TIMEOUT after {time.perf_counter() - start:.0f}s: no answer from the server")
        return None
    except httpx.HTTPError as exc:
        print(f"[{label}] NETWORK ERROR {type(exc).__name__}: {exc}")
        return None
    print(f"[{label}] HTTP {resp.status_code} in {time.perf_counter() - start:.1f}s")
    if resp.status_code >= 400:
        print("   server said:", resp.text[:400].replace("\n", " "))
    return resp


async def main() -> None:
    s = get_settings()
    provider = s.LLM_PROVIDER.lower()
    print(f"provider={provider} model={s.LLM_MODEL!r} key_set={bool(s.LLM_API_KEY)} timeout_setting={s.LLM_TIMEOUT_SECONDS}s")
    if not s.LLM_API_KEY or not s.LLM_MODEL:
        print("-> Fill LLM_API_KEY and LLM_MODEL in backend/.env first.")
        return
    async with httpx.AsyncClient(timeout=TEST_TIMEOUT) as c:
        if provider == "gemini":
            base = "https://generativelanguage.googleapis.com/v1beta"
            h = {"x-goog-api-key": s.LLM_API_KEY}
            r = await timed(c, "list models", "GET", f"{base}/models?pageSize=200", headers=h)
            if r is not None and r.status_code == 200:
                names = sorted(
                    m["name"].removeprefix("models/") for m in r.json().get("models", [])
                    if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in m["name"]
                )
                print("   usable flash models:", ", ".join(names) or "(none)")
                print("   your LLM_MODEL is listed:", s.LLM_MODEL.removeprefix("models/") in names)
            for model in [m.removeprefix("models/") for m in (sys.argv[1:] or [s.LLM_MODEL])]:
                r = await timed(c, f"test call {model}", "POST", f"{base}/models/{model}:generateContent", headers=h,
                                json={"contents": [{"role": "user", "parts": [{"text": "Reply with the single word: pong"}]}]})
                if r is not None and r.status_code == 200:
                    parts = (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [])
                    print("   answer:", "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()[:100] or "(empty)")
        elif provider == "groq":
            h = {"Authorization": f"Bearer {s.LLM_API_KEY}"}
            r = await timed(c, "list models", "GET", "https://api.groq.com/openai/v1/models", headers=h)
            if r is not None and r.status_code == 200:
                print("   models:", ", ".join(sorted(m["id"] for m in r.json().get("data", []))))
            r = await timed(c, "test call", "POST", "https://api.groq.com/openai/v1/chat/completions", headers=h,
                            json={"model": s.LLM_MODEL, "messages": [{"role": "user", "content": "Reply with the single word: pong"}]})
            if r is not None and r.status_code == 200:
                print("   answer:", (r.json()["choices"][0]["message"].get("content") or "").strip()[:100])
        else:
            print("-> LLM_PROVIDER must be gemini or groq")


asyncio.run(main())
