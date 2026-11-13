from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ENV: str = "development"
    DATABASE_URL: str = "postgresql+asyncpg://interviewra:interviewra@localhost:5432/interviewra"
    SECRET_KEY: str = "change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    GUEST_TOKEN_EXPIRE_DAYS: int = 7
    REFRESH_GRACE_DAYS: int = 7  # an expired token can still be exchanged for a new one this long
    CORS_ORIGINS: str = "http://localhost:3000"

    LLM_PROVIDER: str = "gemini"
    LLM_MODEL: str = ""
    LLM_API_KEY: str = ""
    LLM_TIMEOUT_SECONDS: int = 30
    MAX_AGENT_STEPS: int = 6
    HISTORY_WINDOW: int = 12
    ENABLE_PARALLEL_EVAL: bool = False
    STRICT_QUESTION_TAGS: bool = True  # a reply that asks a new main question must wrap the question in <q></q> (else one rewrite)
    ANSWER_JUDGE: bool = True  # one small model call judges whether an answer is wrong/unprofessional (needs a follow-up)
    MAX_UPLOAD_MB: int = 5

    CLEANUP_INTERVAL_HOURS: int = 24  # 0 turns the background cleanup off
    GUEST_RETENTION_DAYS: int = 30  # guests unseen for this long are deleted with all their data
    ABANDON_AFTER_DAYS: int = 3  # still-"active" interviews older than this become "abandoned"
    SESSION_RETENTION_DAYS: int = 365  # registered users' interviews older than this are deleted (0 = keep forever)

    LIMIT_GUEST_INTERVIEWS_PER_DAY: int = 3
    LIMIT_GUEST_MESSAGES_PER_DAY: int = 60
    LIMIT_GUEST_RESUMES_PER_DAY: int = 1
    LIMIT_USER_INTERVIEWS_PER_DAY: int = 10
    LIMIT_USER_MESSAGES_PER_DAY: int = 300
    LIMIT_USER_RESUMES_PER_DAY: int = 5

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        """Force asyncpg driver; map libpq-style params (Neon/Supabase) to asyncpg ones."""
        for prefix in ("postgresql://", "postgres://"):
            if v.startswith(prefix):
                v = "postgresql+asyncpg://" + v[len(prefix):]
        parts = urlsplit(v)
        query = []
        for key, val in parse_qsl(parts.query, keep_blank_values=True):
            if key == "channel_binding":
                continue
            query.append(("ssl" if key == "sslmode" else key, val))
        return urlunsplit(parts._replace(query=urlencode(query)))

    @model_validator(mode="after")
    def _check_prod_secret(self) -> "Settings":
        if self.ENV.lower() == "production" and (
            self.SECRET_KEY.startswith("change-me") or len(self.SECRET_KEY) < 32
        ):
            raise ValueError("SECRET_KEY must be a strong random value (>=32 chars) in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() == "production"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
