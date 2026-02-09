"""Customer assistant service for managing per-customer assistants."""

import json
import re
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from app.prompts.customer import get_customer_prompt
from app.schemas.crm import Customer, Contact, Opportunity, Activity, PromotedActionItem
from app.schemas.enums import CustomerSize, LeadSource
from app.services.backboard import BackboardService
from app.services.cache import CacheService, CACHE_TTLS, build_cache_key
from app.tools.definitions import get_customer_assistant_tools


class CustomerService:
    """Service for managing per-customer assistants and their data."""

    def __init__(self, backboard: BackboardService):
        """Initialize the customer service.

        Args:
            backboard: BackboardService instance
        """
        self._backboard = backboard
        self._cache = CacheService()

    def _generate_assistant_name(self, company_name: str) -> str:
        """Generate a unique assistant name for a customer.

        Args:
            company_name: The company name

        Returns:
            Unique assistant name
        """
        if not company_name:
            company_name = "unknown"
        
        # Normalize for use in name
        normalized = re.sub(r"[^a-zA-Z0-9]", "-", company_name.lower())
        normalized = re.sub(r"-+", "-", normalized).strip("-")
        return f"customer-{normalized}"

    async def create_customer(
        self,
        company_name: str,
        company_domain: str | None = None,
        industry: str | None = None,
        size: CustomerSize | None = None,
        assigned_user_id: str | None = None,
        lead_source: "LeadSource | None" = None,
        lead_source_detail: str | None = None,
    ) -> Customer:
        """Create a new customer with its own assistant.

        Args:
            company_name: The company name
            company_domain: Optional company domain
            industry: Optional industry
            size: Optional company size
            assigned_user_id: Optional user to assign
            lead_source: How this customer was first sourced
            lead_source_detail: Extra context for the lead source

        Returns:
            Created Customer object
        """
        # Generate unique ID and assistant name
        customer_id = str(uuid.uuid4())
        assistant_name = self._generate_assistant_name(company_name)

        # Create the customer assistant
        system_prompt = get_customer_prompt(
            company_name=company_name,
            company_domain=company_domain,
            industry=industry,
        )

        # Create assistant (tools disabled for now - can cause API issues)
        assistant = await self._backboard.create_assistant(
            name=assistant_name,
            system_prompt=system_prompt,
            # tools=get_customer_assistant_tools(),  # Disabled - can cause Backboard API issues
        )

        # Create Customer object
        customer = Customer(
            id=customer_id,
            company_name=company_name,
            domain=company_domain,
            industry=industry,
            size=size,
            assistant_id=assistant.assistant_id,
            lead_source=lead_source,
            lead_source_detail=lead_source_detail,
            assigned_user_id=assigned_user_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        # Store customer in memory (metadata excluded - can cause API issues)
        await self._backboard.add_memory(
            assistant_id=assistant.assistant_id,
            content=customer.to_memory_content(),
        )

        self._cache.invalidate_customer(assistant.assistant_id, include_registry=True)
        return customer

    async def get_customer(self, assistant_id: str) -> Customer | None:
        """Get a customer by their assistant ID.

        Args:
            assistant_id: The customer's Backboard assistant ID

        Returns:
            Customer object if found, None otherwise
        """
        cache_key = build_cache_key("customer", assistant_id)

        async def _build():
            try:
                memories = await self._backboard.get_memories(assistant_id)
                for memory in memories.memories:
                    try:
                        data = json.loads(memory.content)
                        if data.get("id") and data.get("company_name"):
                            return Customer.model_validate(data).model_dump(mode="json")
                    except (json.JSONDecodeError, ValueError):
                        continue
            except Exception:
                pass
            return None

        payload = await self._cache.get_or_set(
            cache_key,
            self._cache.with_jitter(CACHE_TTLS["customer"]),
            _build,
            tags=[f"customer:{assistant_id}"],
        )
        if payload:
            return Customer.model_validate(payload)
        return None

    async def update_customer(
        self,
        assistant_id: str,
        **updates: Any,
    ) -> Customer | None:
        """Update a customer's information.

        Args:
            assistant_id: The customer's assistant ID
            **updates: Fields to update

        Returns:
            Updated Customer object or None if not found
        """
        customer = await self.get_customer(assistant_id)
        if not customer:
            return None

        # Apply updates
        update_data = customer.model_dump()
        update_data.update(updates)
        update_data["updated_at"] = datetime.utcnow()

        updated_customer = Customer.model_validate(update_data)

        # Find and update the customer memory
        memories = await self._backboard.get_memories(assistant_id)
        for memory in memories.memories:
            try:
                data = json.loads(memory.content)
                # Identify customer by structure (same as get_customer)
                if data.get("id") and data.get("company_name") and data.get("assistant_id"):
                    await self._backboard.update_memory(
                        assistant_id=assistant_id,
                        memory_id=memory.id,
                        content=updated_customer.to_memory_content(),
                    )
                    self._cache.invalidate_customer(assistant_id)
                    return updated_customer
            except (json.JSONDecodeError, ValueError):
                continue

        if updated_customer:
            self._cache.invalidate_customer(assistant_id)
        return updated_customer

    async def get_contacts(self, assistant_id: str) -> list[Contact]:
        """Get all contacts for a customer.

        Args:
            assistant_id: The customer's assistant ID

        Returns:
            List of Contact objects
        """
        cache_key = build_cache_key("contacts", assistant_id)

        async def _build():
            contacts = []
            try:
                memories = await self._backboard.get_memories(assistant_id)
                for memory in memories.memories:
                    try:
                        data = json.loads(memory.content)
                        if data.get("customer_id") and data.get("name") and "is_champion" in data:
                            contacts.append(Contact.model_validate(data).model_dump(mode="json"))
                    except (json.JSONDecodeError, ValueError):
                        continue
            except Exception:
                pass
            return contacts

        payload = await self._cache.get_or_set(
            cache_key,
            self._cache.with_jitter(CACHE_TTLS["contacts"]),
            _build,
            tags=[f"customer:{assistant_id}"],
        )
        return [Contact.model_validate(item) for item in payload]

    async def add_contact(
        self,
        assistant_id: str,
        customer_id: str,
        name: str,
        email: str | None = None,
        role: str | None = None,
        linkedin_url: str | None = None,
        is_champion: bool = False,
        is_decision_maker: bool = False,
    ) -> Contact:
        """Add a contact to a customer.

        Args:
            assistant_id: The customer's assistant ID
            customer_id: The customer ID
            name: Contact's full name
            email: Optional email
            role: Optional job title
            linkedin_url: Optional LinkedIn URL
            is_champion: Whether this is our champion
            is_decision_maker: Whether they can make buying decisions

        Returns:
            Created Contact object
        """
        contact = Contact(
            id=str(uuid.uuid4()),
            customer_id=customer_id,
            name=name,
            email=email,
            role=role,
            linkedin_url=linkedin_url,
            is_champion=is_champion,
            is_decision_maker=is_decision_maker,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        # Store contact in memory (metadata excluded - can cause API issues)
        await self._backboard.add_memory(
            assistant_id=assistant_id,
            content=contact.to_memory_content(),
        )

        self._cache.invalidate_customer(assistant_id)
        return contact

    async def get_opportunities(self, assistant_id: str) -> list[Opportunity]:
        """Get all opportunities for a customer.

        Args:
            assistant_id: The customer's assistant ID

        Returns:
            List of Opportunity objects
        """
        cache_key = build_cache_key("opportunities", assistant_id)

        async def _build():
            opportunities = []
            try:
                memories = await self._backboard.get_memories(assistant_id)
                for memory in memories.memories:
                    try:
                        data = json.loads(memory.content)
                        if data.get("customer_id") and data.get("stage") and "confidence" in data:
                            opportunities.append(
                                Opportunity.model_validate(data).model_dump(mode="json")
                            )
                    except (json.JSONDecodeError, ValueError):
                        continue
            except Exception:
                pass
            return opportunities

        payload = await self._cache.get_or_set(
            cache_key,
            self._cache.with_jitter(CACHE_TTLS["opportunities"]),
            _build,
            tags=[f"customer:{assistant_id}"],
        )
        return [Opportunity.model_validate(item) for item in payload]

    async def get_activities(self, assistant_id: str) -> list[Activity]:
        """Get all activities for a customer.

        Args:
            assistant_id: The customer's assistant ID

        Returns:
            List of Activity objects
        """
        cache_key = build_cache_key("activities", assistant_id)

        async def _build():
            activities = []
            try:
                memories = await self._backboard.get_memories(assistant_id)
                for memory in memories.memories:
                    try:
                        data = json.loads(memory.content)
                        if data.get("thread_id") and data.get("activity_type") and data.get("summary"):
                            activities.append(Activity.model_validate(data))
                    except (json.JSONDecodeError, ValueError):
                        continue
            except Exception:
                pass
            activities.sort(key=lambda a: a.date, reverse=True)
            return [a.model_dump(mode="json") for a in activities]

        payload = await self._cache.get_or_set(
            cache_key,
            self._cache.with_jitter(CACHE_TTLS["activities"]),
            _build,
            tags=[f"customer:{assistant_id}"],
        )
        activities = [Activity.model_validate(item) for item in payload]
        activities.sort(key=lambda a: a.date, reverse=True)
        return activities

    async def get_promoted_action_items(
        self,
        assistant_id: str,
        include_dismissed: bool = False,
        limit: int = 50,
    ) -> list[PromotedActionItem]:
        """Get promoted action items for a customer.

        Args:
            assistant_id: The customer's assistant ID
            include_dismissed: If True, include dismissed items
            limit: Maximum number to return

        Returns:
            List of PromotedActionItem objects sorted by created_at descending
        """
        cache_key = build_cache_key(
            "action_items",
            assistant_id,
            "include" if include_dismissed else "active",
            str(limit),
        )

        async def _build():
            items = []
            try:
                memories = await self._backboard.get_memories(assistant_id)
                for memory in memories.memories:
                    try:
                        data = json.loads(memory.content)
                        if (
                            data.get("activity_id")
                            and data.get("thread_id")
                            and "source_excerpt" in data
                            and "is_dismissed" in data
                        ):
                            item = PromotedActionItem.model_validate(data)
                            if not include_dismissed and item.is_dismissed:
                                continue
                            items.append(item)
                    except (json.JSONDecodeError, ValueError):
                        continue
            except Exception:
                pass
            items.sort(key=lambda i: i.created_at, reverse=True)
            return [i.model_dump(mode="json") for i in items[:limit]]

        payload = await self._cache.get_or_set(
            cache_key,
            self._cache.with_jitter(CACHE_TTLS["action_items"]),
            _build,
            tags=[f"customer:{assistant_id}"],
        )
        return [PromotedActionItem.model_validate(item) for item in payload]

    async def get_customer_summary(self, assistant_id: str) -> dict[str, Any]:
        """Get a comprehensive summary of a customer.

        Args:
            assistant_id: The customer's assistant ID

        Returns:
            Dict with customer, contacts, opportunities, recent activities, action items
        """
        cache_key = build_cache_key("customer_summary", assistant_id)

        async def _build():
            customer = await self.get_customer(assistant_id)
            contacts = await self.get_contacts(assistant_id)
            opportunities = await self.get_opportunities(assistant_id)
            activities = await self.get_activities(assistant_id)
            action_items = await self.get_promoted_action_items(assistant_id, limit=50)

            recent_activities = activities[:10]
            recent_action_items = action_items[:3]

            return {
                "customer": customer.model_dump(mode="json") if customer else None,
                "contacts": [c.model_dump(mode="json") for c in contacts],
                "opportunities": [o.model_dump(mode="json") for o in opportunities],
                "recent_activities": [a.model_dump(mode="json") for a in recent_activities],
                "recent_action_items": [i.model_dump(mode="json") for i in recent_action_items],
                "stats": {
                    "total_contacts": len(contacts),
                    "total_opportunities": len(opportunities),
                    "total_activities": len(activities),
                    "total_action_items": len(action_items),
                    "pending_action_items": sum(1 for i in action_items if not i.is_completed),
                    "champions": sum(1 for c in contacts if c.is_champion),
                    "decision_makers": sum(1 for c in contacts if c.is_decision_maker),
                },
            }

        return await self._cache.get_or_set(
            cache_key,
            self._cache.with_jitter(CACHE_TTLS["customer_summary"]),
            _build,
            tags=[f"customer:{assistant_id}"],
        )

    async def get_pain_points(self, assistant_id: str) -> list[str]:
        """Extract all pain points mentioned across activities.

        Args:
            assistant_id: The customer's assistant ID

        Returns:
            List of unique pain points
        """
        pain_points = set()
        try:
            memories = await self._backboard.get_memories(assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    # Check if this is a meeting summary by looking for specific fields
                    if data.get("type") == "meeting_summary" and "pain_points" in data:
                        pain_points.update(data["pain_points"])
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass
        return list(pain_points)

    async def get_recent_topics(self, assistant_id: str, limit: int = 5) -> list[str]:
        """Get recent discussion topics from activities.

        Args:
            assistant_id: The customer's assistant ID
            limit: Maximum number of topics to return

        Returns:
            List of recent topics/labels
        """
        topics = []
        try:
            memories = await self._backboard.get_memories(assistant_id)
            summaries = []
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    # Check if this is a meeting summary by looking for specific fields
                    if data.get("type") == "meeting_summary":
                        summaries.append(data)
                except (json.JSONDecodeError, ValueError):
                    continue

            # Sort by date and extract labels
            summaries.sort(key=lambda x: x.get("date", ""), reverse=True)
            for summary in summaries[:limit]:
                topics.extend(summary.get("labels", []))
        except Exception:
            pass
        return topics[:limit]

    async def get_customer_next_followup(self, assistant_id: str) -> date | None:
        """Get next follow-up date, calculating from last activity if not set.

        Args:
            assistant_id: The customer's assistant ID

        Returns:
            Next follow-up date, or None if no activities exist
        """
        customer = await self.get_customer(assistant_id)
        if customer and customer.next_followup_date:
            return customer.next_followup_date

        # Auto-calculate: 2 weeks from last activity
        activities = await self.get_activities(assistant_id)
        if activities:
            last_activity = activities[0]  # Already sorted by date descending
            return (last_activity.date + timedelta(days=14)).date()

        return None

    async def set_customer_followup_date(
        self,
        assistant_id: str,
        followup_date: date | None,
    ) -> Customer | None:
        """Set the customer's next follow-up date.

        Args:
            assistant_id: The customer's assistant ID
            followup_date: The follow-up date to set (None to clear)

        Returns:
            Updated Customer object or None if not found
        """
        return await self.update_customer(
            assistant_id,
            next_followup_date=followup_date,
        )

    async def assign_customer(
        self,
        assistant_id: str,
        user_id: str | None,
    ) -> Customer | None:
        """Assign a customer to a user.

        Args:
            assistant_id: The customer's assistant ID
            user_id: The user ID to assign (None to unassign)

        Returns:
            Updated Customer object or None if not found
        """
        return await self.update_customer(
            assistant_id,
            assigned_user_id=user_id,
        )

    async def get_customers_with_followups_today(
        self,
        customer_registry: list[dict[str, str]],
        assigned_user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get customers with follow-ups due today or overdue.

        Args:
            customer_registry: List of {company_name, assistant_id} dicts
            assigned_user_id: If provided, only return customers assigned to this user

        Returns:
            List of customers with follow-ups due today, including customer data
            and contact count
        """
        today = date.today()
        results = []

        for entry in customer_registry:
            assistant_id = entry["assistant_id"]
            try:
                customer = await self.get_customer(assistant_id)
                if not customer:
                    continue

                # Filter by assigned user if specified
                if assigned_user_id is not None and customer.assigned_user_id != assigned_user_id:
                    continue

                followup_date = await self.get_customer_next_followup(assistant_id)
                if followup_date and followup_date <= today:
                    contacts = await self.get_contacts(assistant_id)
                    results.append({
                        "customer": customer.model_dump(mode="json"),
                        "followup_date": followup_date.isoformat(),
                        "is_overdue": followup_date < today,
                        "contact_count": len(contacts),
                    })
            except Exception:
                continue

        # Sort by follow-up date (oldest first, most overdue at top)
        results.sort(key=lambda x: x["followup_date"])
        return results


def get_customer_service(backboard: BackboardService) -> CustomerService:
    """Get a CustomerService instance.

    Args:
        backboard: BackboardService instance to use

    Returns:
        CustomerService instance
    """
    return CustomerService(backboard)
