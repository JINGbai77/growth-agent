from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GROWTH_", env_file=".env", extra="ignore")

    llm_enabled: bool = False
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    llm_timeout_seconds: float = Field(default=20, gt=0, le=120)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    database_path: str = "var/growth.sqlite3"
    max_pending_jobs: int = Field(default=16, ge=1, le=100)
    job_workers: int = Field(default=2, ge=1, le=8)

    @field_validator("ollama_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("ollama_url must be an http(s) server URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("ollama_url must not contain credentials, queries or fragments")
        return value.rstrip("/")
