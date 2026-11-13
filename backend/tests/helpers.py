import json
from typing import Any

from httpx import AsyncClient, Response

from tests.conftest import bearer

API = "/api/v1"
BODY = {"role_name": "Backend Engineer", "level": "junior", "interview_type": "technical", "question_count": 3}

REPORT: dict[str, Any] = {
    "internal_analysis": "private reasoning",
    "overall_score": 72,
    "category_scores": {"technical_accuracy": 70, "communication": 75, "depth": 68, "problem_solving": 74},
    "summary": "Solid junior answers with room to go deeper.",
    "strengths": ["Clear explanations", "Used concrete examples"],
    "weaknesses": ["Little discussion of trade-offs", "Skipped edge cases"],
    "per_question": [
        {"question": "What is an index?", "answer_summary": "Speeds up reads.", "score": 70,
         "feedback": "Correct but shallow.", "better_answer_hint": "Mention write cost."}
    ],
    "improvement_tips": ["Name a trade-off for every choice", "Practice STAR", "Study query plans"],
    "recommended_topics": ["Indexing", "Transactions", "Caching"],
}


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def guest(client: AsyncClient) -> dict[str, str]:
    r = await client.post(f"{API}/auth/guest")
    assert r.status_code == 201
    return bearer(r.json()["access_token"])


async def start(client: AsyncClient, headers: dict[str, str], **overrides: Any) -> Response:
    return await client.post(f"{API}/interviews", json={**BODY, **overrides}, headers=headers)


async def start_ok(client: AsyncClient, headers: dict[str, str], **overrides: Any) -> str:
    r = await start(client, headers, **overrides)
    assert r.status_code == 200, r.text
    return parse_sse(r.text)[0][1]["session_id"]
