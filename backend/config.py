from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentConfig(BaseModel):
    """Configuration for a single LLM agent."""
    
    name: str = Field(..., description="Unique name for this agent")
    system_prompt: str = Field(..., description="System prompt for this agent")
    model: str = Field(..., description="Model name to use for this agent")
    description: str = Field(default="", description="Human-readable description of agent's purpose")


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    openrouter_api_key: str = Field(..., env="OPENROUTER_API_KEY")
    openrouter_model: str = Field(
        default="openrouter/anthropic/claude-3.5-sonnet",
        env="OPENROUTER_MODEL",
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        env="OPENROUTER_BASE_URL",
    )
    session_ttl_seconds: int = Field(default=3600, env="SESSION_TTL_SECONDS")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    allow_origins: list[str] = Field(default_factory=lambda: ["*"], env="ALLOW_ORIGINS")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
