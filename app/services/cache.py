"""In-process TTL cache service for CloserNotes.

Stores cached data in a module-level dict so it persists across requests
within the same worker process. Cache lookups are instant (no network).
Only cache misses hit Backboard.
"""

import logging
import random
import time
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field


CACHE_TTLS: dict[str, int] = {
    "registry": 600,
    "customer": 300,
    "contacts": 300,
    "opportunities": 300,
    "activities": 300,
    "action_items": 300,
    "customer_summary": 300,
    "dashboard": 180,
    "manager_dashboard": 180,
    "global_contacts": 180,
    "global_opportunities": 180,
    "global_activities": 180,
}


def build_cache_key(*parts: str) -> str:
    """Build a consistent cache key."""
    joined = ":".join(p.strip(":") for p in parts if p)
    return f"cache:v1:{joined}"


class _CacheSlot(BaseModel):
    """Single cached value with metadata."""

    payload: Any
    expires_at: float
    tags: list[str] = Field(default_factory=list)


# Module-level store: survives across requests in the same worker process.
_store: dict[str, _CacheSlot] = {}
# Reverse index: tag -> set of keys for fast invalidation.
_tag_index: dict[str, set[str]] = {}

_logger = logging.getLogger(__name__)


class CacheService:
    """In-process TTL cache with tag-based invalidation.

    No network calls for reads or invalidation -- only the builder
    callable (on cache miss) touches Backboard.
    """

    _NOT_FOUND = object()

    def with_jitter(self, ttl_seconds: int, pct: float = 0.1) -> int:
        if ttl_seconds <= 0:
            return ttl_seconds
        jitter = ttl_seconds * pct
        return int(ttl_seconds + random.uniform(-jitter, jitter))

    # -- core operations ---------------------------------------------------

    def get(self, key: str) -> Any:
        slot = _store.get(key)
        if slot is None:
            _logger.debug("cache_miss key=%s", key)
            return self._NOT_FOUND

        if time.monotonic() >= slot.expires_at:
            _evict(key)
            _logger.debug("cache_expired key=%s", key)
            return self._NOT_FOUND

        _logger.debug("cache_hit key=%s", key)
        return slot.payload

    def set(
        self,
        key: str,
        payload: Any,
        ttl_seconds: int,
        tags: list[str] | None = None,
    ) -> None:
        tags = tags or []
        _store[key] = _CacheSlot(
            payload=payload,
            expires_at=time.monotonic() + ttl_seconds,
            tags=tags,
        )
        for tag in tags:
            _tag_index.setdefault(tag, set()).add(key)

    async def get_or_set(
        self,
        key: str,
        ttl_seconds: int,
        builder: Callable[[], Awaitable[Any]],
        tags: list[str] | None = None,
    ) -> Any:
        cached = self.get(key)
        if cached is not self._NOT_FOUND:
            return cached

        payload = await builder()
        self.set(key, payload, ttl_seconds, tags=tags)
        return payload

    # -- invalidation ------------------------------------------------------

    def invalidate_by_key(self, key: str) -> int:
        if key in _store:
            _evict(key)
            return 1
        return 0

    def invalidate_by_tag(self, tag: str) -> int:
        return self.invalidate_by_tags([tag])

    def invalidate_by_tags(self, tags: list[str]) -> int:
        deleted = 0
        for tag in tags:
            keys = _tag_index.pop(tag, set())
            for key in keys:
                if key in _store:
                    _evict(key)
                    deleted += 1
        return deleted

    def invalidate_customer(self, assistant_id: str, include_registry: bool = False) -> None:
        tags = [f"customer:{assistant_id}", "dashboards", "global_lists"]
        if include_registry:
            tags.append("registry")
        self.invalidate_by_tags(tags)


def _evict(key: str) -> None:
    """Remove a key from the store and clean up tag index."""
    slot = _store.pop(key, None)
    if slot:
        for tag in slot.tags:
            tag_keys = _tag_index.get(tag)
            if tag_keys:
                tag_keys.discard(key)
                if not tag_keys:
                    del _tag_index[tag]
