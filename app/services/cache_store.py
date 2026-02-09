"""Cache store service — manages denormalized customer summaries on the cache assistant.

Reads: one get_memories() call returns all customer summaries.
Writes: called after any CRM mutation to keep the cache fresh.
"""

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

from app.config import get_settings
from app.schemas.cache import CachedCustomerSummary
from app.services.backboard import BackboardService
from app.services.cache import CacheService

_logger = logging.getLogger(__name__)


class CacheStoreService:
    """Manages denormalized customer summaries stored on the cache assistant."""

    def __init__(self, backboard: BackboardService):
        self._backboard = backboard
        self._cache_assistant_id = get_settings().cache_assistant_id
        self._cache = CacheService()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_all_summaries(self) -> list[CachedCustomerSummary]:
        """Return every customer summary from the cache assistant.

        Single Backboard API call.  Results are parsed and returned
        unsorted — callers filter/sort as needed.
        """
        try:
            memories = await self._backboard.get_memories(self._cache_assistant_id)
            summaries: list[CachedCustomerSummary] = []
            for memory in getattr(memories, "memories", []):
                try:
                    data = json.loads(memory.content)
                    if data.get("type") != "customer_summary":
                        continue
                    summary = CachedCustomerSummary.model_validate(data)
                    # Attach the Backboard memory ID so we can update later
                    summary.memory_id = (
                        getattr(memory, "memory_id", None)
                        or getattr(memory, "id", None)
                    )
                    if summary.memory_id is not None:
                        summary.memory_id = str(summary.memory_id)
                    summaries.append(summary)
                except (json.JSONDecodeError, ValueError):
                    continue
            return summaries
        except Exception:
            _logger.exception("Failed to load summaries from cache assistant")
            return []

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    async def update_customer_summary(self, assistant_id: str) -> None:
        """Rebuild and persist the summary for a single customer.

        Reads fresh data from the per-customer assistant, then writes
        (or updates) the corresponding memory on the cache assistant.
        """
        from app.services.customer import CustomerService

        customer_svc = CustomerService(self._backboard)

        customer = await customer_svc.get_customer(assistant_id)
        if not customer:
            # Customer was deleted or not found — remove stale cache entry
            await self.delete_customer_summary(assistant_id)
            return

        contacts = await customer_svc.get_contacts(assistant_id)
        opportunities = await customer_svc.get_opportunities(assistant_id)
        activities = await customer_svc.get_activities(assistant_id)
        action_items = await customer_svc.get_promoted_action_items(
            assistant_id, include_dismissed=False, limit=50,
        )

        # Compute next follow-up (explicit or auto from last activity)
        next_followup = customer.next_followup_date
        if not next_followup and activities:
            last_date = activities[0].date
            next_followup = (last_date + timedelta(days=14)).date()

        last_activity_date: date | None = None
        if activities:
            d = activities[0].date
            last_activity_date = d.date() if isinstance(d, datetime) else d

        summary = CachedCustomerSummary(
            customer_id=customer.id,
            assistant_id=assistant_id,
            company_name=customer.company_name,
            domain=customer.domain,
            industry=customer.industry,
            size=customer.size.value if customer.size else None,
            assigned_user_id=customer.assigned_user_id,
            created_at=customer.created_at,
            updated_at=customer.updated_at,
            next_followup_date=next_followup,
            opportunity_count=len(opportunities),
            activity_count=len(activities),
            contact_count=len(contacts),
            pending_action_items=sum(1 for i in action_items if not i.is_completed),
            last_activity_date=last_activity_date,
            cached_at=datetime.utcnow(),
        )

        await self._upsert_summary(summary)
        # Bust in-process cache so next request sees fresh data
        self._cache.invalidate_by_tags(["dashboards", "global_lists"])

    async def delete_customer_summary(self, assistant_id: str) -> None:
        """Remove the cached summary for a customer."""
        try:
            memories = await self._backboard.get_memories(self._cache_assistant_id)
            for memory in getattr(memories, "memories", []):
                try:
                    data = json.loads(memory.content)
                    if (
                        data.get("type") == "customer_summary"
                        and data.get("assistant_id") == assistant_id
                    ):
                        memory_id = (
                            getattr(memory, "memory_id", None)
                            or getattr(memory, "id", None)
                        )
                        if memory_id:
                            await self._backboard.delete_memory(
                                self._cache_assistant_id, str(memory_id),
                            )
                        break
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            _logger.exception("Failed to delete cache summary for %s", assistant_id)

        self._cache.invalidate_by_tags(["dashboards", "global_lists"])

    async def rebuild_all(
        self, registry: list[dict[str, str]],
    ) -> int:
        """Full rebuild: update every customer in the registry.

        Args:
            registry: list of {company_name, assistant_id} dicts

        Returns:
            Number of summaries written.
        """
        count = 0
        for entry in registry:
            try:
                await self.update_customer_summary(entry["assistant_id"])
                count += 1
            except Exception:
                _logger.exception(
                    "Failed to rebuild summary for %s", entry.get("assistant_id"),
                )
        return count

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _upsert_summary(self, summary: CachedCustomerSummary) -> None:
        """Create or update the summary memory on the cache assistant."""
        content = summary.model_dump_json()

        # Try to find an existing memory for this customer
        try:
            memories = await self._backboard.get_memories(self._cache_assistant_id)
            for memory in getattr(memories, "memories", []):
                try:
                    data = json.loads(memory.content)
                    if (
                        data.get("type") == "customer_summary"
                        and data.get("assistant_id") == summary.assistant_id
                    ):
                        memory_id = (
                            getattr(memory, "memory_id", None)
                            or getattr(memory, "id", None)
                        )
                        if memory_id:
                            await self._backboard.update_memory(
                                assistant_id=self._cache_assistant_id,
                                memory_id=str(memory_id),
                                content=content,
                            )
                            return
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            _logger.exception("Error searching for existing cache memory")

        # No existing memory — create a new one
        await self._backboard.add_memory(
            assistant_id=self._cache_assistant_id,
            content=content,
        )


def get_cache_store(backboard: BackboardService) -> CacheStoreService:
    """Factory for CacheStoreService."""
    return CacheStoreService(backboard)
