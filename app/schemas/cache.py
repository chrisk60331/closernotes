"""Cached customer summary schema for the cache assistant."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class CachedCustomerSummary(BaseModel):
    """Pre-computed customer summary stored on the cache assistant.

    One memory per customer (~500 bytes). Used by dashboard and
    manager dashboard views to avoid N+1 Backboard API calls.

    Note: Backboard memories have a 4 KB content limit, so we store
    only counts and metadata here — no denormalized object lists.
    Global list views (contacts/opps/activities) still read from
    per-customer assistants via the in-process cache.
    """

    type: Literal["customer_summary"] = "customer_summary"
    customer_id: str
    assistant_id: str  # per-customer Backboard assistant ID
    company_name: str
    domain: str | None = None
    industry: str | None = None
    size: str | None = None
    assigned_user_id: str | None = None  # key for permission filtering
    created_at: datetime | None = None
    updated_at: datetime | None = None
    next_followup_date: date | None = None

    # Denormalized counts
    opportunity_count: int = 0
    activity_count: int = 0
    contact_count: int = 0
    pending_action_items: int = 0
    last_activity_date: date | None = None

    # Memory tracking
    memory_id: str | None = None  # Backboard memory ID for updates
    cached_at: datetime = Field(default_factory=datetime.utcnow)
