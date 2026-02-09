"""Configuration settings for CloserNotes."""

import asyncio
import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

_logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignore extra env vars
    )

    # Backboard.io
    backboard_api_key: str

    # Assistant IDs (optional — auto-created if not provided)
    # Supply separate IDs for each, or leave blank to auto-create a single
    # shared assistant that is reused for all three.
    orchestrator_assistant_id: str | None = None
    users_assistant_id: str | None = None
    cache_assistant_id: str | None = None

    # Optional: Newsboard assistant for follow-up email generation
    newsboard_assistant_id: str | None = None

    # LLM defaults
    default_llm_provider: str = "openai"
    default_model: str = "gpt-4o"

    # Flask
    flask_secret_key: str = "dev-secret-key-change-in-production"
    flask_env: str = "development"

    # Whisper transcription settings
    # Model sizes: tiny, base, small, medium, large-v3
    # Larger models are more accurate but slower
    # "small" recommended for microphone recordings
    whisper_model: str = "small"


# ---------------------------------------------------------------------------
# Auto-provisioning helpers
# ---------------------------------------------------------------------------

_DEFAULT_ASSISTANT_NAME = "CloserNotes"
_DEFAULT_ASSISTANT_DESCRIPTION = "Multi-purpose assistant for CloserNotes CRM."


async def _create_default_assistant(api_key: str) -> str:
    """Create a shared CloserNotes assistant on Backboard.

    Uses BackboardClient directly (not BackboardService) to avoid a
    circular call back into get_settings().

    Returns:
        The newly created assistant ID as a string.
    """
    from backboard import BackboardClient

    async with BackboardClient(api_key=api_key) as client:
        result = await client.create_assistant(
            name=_DEFAULT_ASSISTANT_NAME,
            description=_DEFAULT_ASSISTANT_DESCRIPTION,
        )
    # result may be an object or dict depending on SDK version
    assistant_id = (
        getattr(result, "assistant_id", None)
        or (result.get("assistant_id") if isinstance(result, dict) else None)
    )
    assistant_id = str(assistant_id)
    _logger.info("Auto-created shared Backboard assistant: %s", assistant_id)
    return assistant_id


def _run_sync(async_fn, *args):
    """Run an async callable from a synchronous context.

    Accepts the async *function* (not an already-created coroutine) so that
    a fresh coroutine can be created for each execution strategy.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # Already inside an event loop — run in a worker thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, async_fn(*args)).result()

    # No running loop — safe to use asyncio.run directly
    return asyncio.run(async_fn(*args))


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_resolved_settings: Settings | None = None


def get_settings() -> Settings:
    """Get application settings singleton.

    On the first call, any missing assistant IDs are resolved by
    auto-creating a single shared Backboard assistant and reusing its ID
    for every slot that was left blank.
    """
    global _resolved_settings
    if _resolved_settings is not None:
        return _resolved_settings

    settings = Settings()

    # Treat both None and empty-string as "not provided"
    missing: list[str] = []
    if not settings.orchestrator_assistant_id:
        missing.append("orchestrator")
    if not settings.users_assistant_id:
        missing.append("users")
    if not settings.cache_assistant_id:
        missing.append("cache")

    if missing:
        _logger.info(
            "Assistant IDs missing for [%s] — auto-creating shared assistant",
            ", ".join(missing),
        )
        shared_id = _run_sync(
            _create_default_assistant, settings.backboard_api_key
        )
        if not settings.orchestrator_assistant_id:
            settings.orchestrator_assistant_id = shared_id
        if not settings.users_assistant_id:
            settings.users_assistant_id = shared_id
        if not settings.cache_assistant_id:
            settings.cache_assistant_id = shared_id
    else:
        _logger.info("All assistant IDs provided — skipping auto-creation")

    _resolved_settings = settings
    return _resolved_settings
