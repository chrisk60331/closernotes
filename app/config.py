"""Configuration settings for CloserNotes."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignore extra env vars
    )

    # Backboard.io
    backboard_api_key: str
    # Newsboard assistant ID - accepts either NEWSBOARD_ASSISTANT_ID or BACKBOARD_ASSISTANT_ID
    newsboard_assistant_id: str | None = Field(
        default=None,
        validation_alias="NEWSBOARD_ASSISTANT_ID",
    )
    backboard_assistant_id: str | None = Field(
        default=None,
        description="Alias for newsboard_assistant_id",
    )

    # LLM defaults
    default_llm_provider: str = "openai"
    default_model: str = "gpt-4o"

    # Flask
    flask_secret_key: str = "dev-secret-key-change-in-production"
    flask_env: str = "development"

    # Orchestrator assistant name (will be created if not exists)
    orchestrator_assistant_name: str = "closernotes-orchestrator"

    # Whisper transcription settings
    # Model sizes: tiny, base, small, medium, large-v3
    # Larger models are more accurate but slower
    # "small" recommended for microphone recordings
    whisper_model: str = "small"

    @property
    def effective_newsboard_id(self) -> str | None:
        """Get the newsboard assistant ID from either env var."""
        return self.newsboard_assistant_id or self.backboard_assistant_id


def get_settings() -> Settings:
    """Get application settings singleton."""
    return Settings()
