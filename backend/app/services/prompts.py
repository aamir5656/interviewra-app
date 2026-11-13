import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_CLOSING_TAG = re.compile(r"</\s*(transcript|resume_summary|resume|turns|candidate_profile|memory|conversation|candidate_answer|analyses)\b", re.I)


def fence_safe(value: Any) -> str:
    """Make untrusted text safe to place between <tag>...</tag> delimiters: it cannot close our block early."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return _CLOSING_TAG.sub(lambda m: "<\\/" + m.group(1), text)


@lru_cache
def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(PROMPTS_DIR)),
        undefined=StrictUndefined,  # a missing variable is a bug, not an empty string
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        auto_reload=False,
    )
    env.filters["fence_safe"] = fence_safe
    return env


def render(name: str, **variables: Any) -> str:
    """Render app/prompts/<name>.md (templates are compiled once and cached)."""
    if not name.endswith(".md"):
        name += ".md"
    return _env().get_template(name).render(**variables).strip()
