"""The fixed list of interview roles. The API accepts only these names; the question bank has questions for each."""
import re

ROLES: tuple[str, ...] = (
    "Frontend Developer",
    "Backend Engineer",
    "Full-Stack Developer",
    "Data Analyst",
    "DevOps Engineer",
    "QA Engineer",
    "Product Manager",
)


def role_id(name: str) -> str:
    """Stable slug of a role name, for example 'Backend Engineer' -> 'backend-engineer'."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


ROLE_IDS: dict[str, str] = {role_id(r): r for r in ROLES}


def canonical_role(value: str) -> str | None:
    """The official name for a role id or a role name (any case), else None."""
    key = role_id(value)
    return ROLE_IDS.get(key)
