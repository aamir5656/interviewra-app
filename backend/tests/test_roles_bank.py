"""Every dropdown role gets questions that belong to it, for every level and type."""
import random
from collections import Counter

import pytest

from app.roles import ROLES, canonical_role, role_id
from app.services.tools import _pool, _tracks_for, load_bank

DEV_ONLY = {"Merge conflicts", "Why branches", "Code review", "Debugging approach", "Automated tests"}
LEVELS = ("intern", "junior", "mid", "senior")


def test_role_ids_are_stable_and_unique() -> None:
    assert role_id("Backend Engineer") == "backend-engineer" and role_id("Full-Stack Developer") == "full-stack-developer"
    assert len({role_id(r) for r in ROLES}) == len(ROLES) == 7
    assert canonical_role("QA ENGINEER") == "QA Engineer" and canonical_role("Chef") is None


@pytest.mark.parametrize("role", ROLES)
def test_each_role_has_a_real_track(role: str) -> None:
    assert _tracks_for(role), role


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("itype", ["technical", "behavioral", "hr", "mixed"])
def test_enough_topics_for_every_combination(role: str, level: str, itype: str) -> None:
    topics = {q["topic"] for q in _pool(role, level, itype, 0)}
    assert len(topics) >= 15, (role, level, itype, len(topics))


@pytest.mark.parametrize("role", ["Data Analyst", "Product Manager"])
def test_non_developer_roles_never_get_developer_questions(role: str) -> None:
    for seed in range(40):
        rng = random.Random(f"{role}:{seed}")
        for level in LEVELS:
            for index in range(10):
                top = _pool(role, level, "technical", index, rng)[:5]
                assert not any(q["topic"] in DEV_ONLY for q in top), (role, level, [q["topic"] for q in top])
    assert not any(q["topic"] in DEV_ONLY for q in _pool(role, "junior", "technical", 0))
    assert all(q["track"] in ("general", *_tracks_for(role)) for q in _pool(role, "mid", "technical", 0))


def test_developer_roles_do_get_general_dev_questions() -> None:
    topics = {q["topic"] for q in _pool("Backend Engineer", "junior", "technical", 0)}
    assert DEV_ONLY & topics


def test_intern_never_starts_with_a_hard_question_and_topics_vary() -> None:
    for role in ROLES:
        firsts = Counter()
        for i in range(40):
            first = _pool(role, "intern", "technical", 0, random.Random(f"{role}-{i}:0"))[0]
            assert first["difficulty"] == "easy", (role, first["topic"])
            firsts[first["topic"]] += 1
        assert len(firsts) >= 4, role


def test_bank_has_no_duplicate_topics_and_one_focus() -> None:
    bank = load_bank()
    assert len({q["topic"].lower() for q in bank}) == len(bank)
    import re

    joined = re.compile(r",?\s+and\s+(how|what|when|why|which|where|would|do you|did you|can you)\b", re.I)
    assert all(q["question"].count("?") <= 1 and not joined.search(q["question"]) for q in bank)
