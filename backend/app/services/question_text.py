"""Pure helpers for the text of a main question (no imports from other services, so any module can use them)."""
import re

Q_TAG = re.compile(r"<q>\s*(.*?)\s*</q>", re.I | re.S)
Q_MARK = re.compile(r"</?q>", re.I)


def strip_q_tags(text: str) -> str:
    return Q_MARK.sub("", text).strip()


def split_question(text: str) -> tuple[str, str | None]:
    """(text to show, the question) of a reply whose question is wrapped in <q>...</q>.

    The question is exactly what is inside the LAST pair of tags; the text before it is the lead-in. The tags never
    reach the candidate. Without usable tags the question is None (the caller falls back to `extract_question`).
    """
    found = list(Q_TAG.finditer(text))
    if not found or not found[-1].group(1).strip():
        return strip_q_tags(text), None
    last = found[-1]
    question = " ".join(last.group(1).split())
    lead = strip_q_tags(text[: last.start()])
    return (f"{lead}\n\n{question}" if lead else question), question


def question_of(content: str, tool_calls: object) -> str:
    """The main question of a stored interviewer message: the question saved with it, else a best guess from the text."""
    for call in tool_calls or []:  # type: ignore[union-attr]
        if isinstance(call, dict) and call.get("name") == "get_next_topic":
            saved = (call.get("arguments") or {}).get("question")
            if isinstance(saved, str) and saved.strip():
                return saved.strip()
    return extract_question(content or "")


def extract_question(text: str) -> str:
    """The main question inside an interviewer message: its last paragraph that contains a '?' (else the last such sentence)."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    if len(paragraphs) > 1:  # the question is written as its own last paragraph
        for p in reversed(paragraphs):
            if "?" in p:
                return p
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if "?" in s]
    return sentences[-1] if sentences else text.strip()
