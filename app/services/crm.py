"""CRM service for managing CRM objects via Backboard memory."""

import json
import uuid
from datetime import date, datetime
from typing import Any

from app.schemas.crm import (
    Contact,
    ContactCreate,
    ContactUpdate,
    Opportunity,
    OpportunityCreate,
    OpportunityUpdate,
    Activity,
    ActionItem,
    PromotedActionItem,
    PromotedActionItemUpdate,
)
from app.schemas.enums import ActivityType, ContactMethod, OpportunityStage
from app.services.backboard import BackboardService


class CRMService:
    """Service for CRM object CRUD operations via Backboard memory."""

    def __init__(self, backboard: BackboardService):
        """Initialize the CRM service.

        Args:
            backboard: BackboardService instance
        """
        self._backboard = backboard

    # Contact operations
    async def create_contact(
        self,
        assistant_id: str,
        data: ContactCreate,
    ) -> Contact:
        """Create a new contact.

        Args:
            assistant_id: Customer assistant ID
            data: Contact creation data

        Returns:
            Created Contact object
        """
        contact = Contact(
            id=str(uuid.uuid4()),
            customer_id=data.customer_id,
            name=data.name,
            email=data.email,
            phone=data.phone,
            role=data.role,
            linkedin_url=data.linkedin_url,
            is_champion=data.is_champion,
            is_decision_maker=data.is_decision_maker,
            preferred_contact_method=data.preferred_contact_method,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        # Store contact in memory (metadata excluded - can cause API issues)
        await self._backboard.add_memory(
            assistant_id=assistant_id,
            content=contact.to_memory_content(),
        )

        return contact

    async def get_contact(
        self,
        assistant_id: str,
        contact_id: str,
    ) -> Contact | None:
        """Get a contact by ID.

        Args:
            assistant_id: Customer assistant ID
            contact_id: Contact ID to find

        Returns:
            Contact if found, None otherwise
        """
        try:
            memories = await self._backboard.get_memories(assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    # Check if this is a contact and matches the ID
                    if data.get("id") == contact_id and "is_champion" in data:
                        return Contact.model_validate(data)
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass
        return None

    async def list_contacts(
        self,
        assistant_id: str,
    ) -> list[Contact]:
        """List all contacts for a customer.

        Args:
            assistant_id: Customer assistant ID

        Returns:
            List of Contact objects
        """
        contacts = []
        try:
            memories = await self._backboard.get_memories(assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    # Check if this is a contact by looking for contact-specific fields
                    if data.get("customer_id") and data.get("name") and "is_champion" in data:
                        contacts.append(Contact.model_validate(data))
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass
        return contacts

    async def update_contact(
        self,
        assistant_id: str,
        contact_id: str,
        **updates: Any,
    ) -> Contact | None:
        """Update a contact.

        Args:
            assistant_id: Customer assistant ID
            contact_id: Contact ID to update
            **updates: Fields to update

        Returns:
            Updated Contact or None if not found
        """
        try:
            memories = await self._backboard.get_memories(assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    # Check if this is a contact and matches the ID
                    if data.get("id") == contact_id and "is_champion" in data:
                        data.update(updates)
                        data["updated_at"] = datetime.utcnow().isoformat()

                        updated_contact = Contact.model_validate(data)
                        await self._backboard.update_memory(
                            assistant_id=assistant_id,
                            memory_id=memory.id,
                            content=updated_contact.to_memory_content(),
                        )
                        return updated_contact
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass
        return None

    async def delete_contact(
        self,
        assistant_id: str,
        contact_id: str,
    ) -> bool:
        """Delete a contact.

        Args:
            assistant_id: Customer assistant ID
            contact_id: Contact ID to delete

        Returns:
            True if deleted, False otherwise
        """
        try:
            memories = await self._backboard.get_memories(assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    # Check if this is a contact and matches the ID
                    if data.get("id") == contact_id and "is_champion" in data:
                        await self._backboard.delete_memory(assistant_id, memory.id)
                        return True
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass
        return False

    # Opportunity operations
    async def create_opportunity(
        self,
        assistant_id: str,
        data: OpportunityCreate,
    ) -> Opportunity:
        """Create a new opportunity.

        Args:
            assistant_id: Customer assistant ID
            data: Opportunity creation data

        Returns:
            Created Opportunity object
        """
        opportunity = Opportunity(
            id=str(uuid.uuid4()),
            customer_id=data.customer_id,
            name=data.name,
            stage=data.stage,
            value=data.value,
            close_date_estimate=data.close_date_estimate,
            confidence=data.confidence,
            competitors=data.competitors,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        # Store opportunity in memory (metadata excluded - can cause API issues)
        await self._backboard.add_memory(
            assistant_id=assistant_id,
            content=opportunity.to_memory_content(),
        )

        return opportunity

    async def get_opportunity(
        self,
        assistant_id: str,
        opportunity_id: str,
    ) -> Opportunity | None:
        """Get an opportunity by ID.

        Args:
            assistant_id: Customer assistant ID
            opportunity_id: Opportunity ID to find

        Returns:
            Opportunity if found, None otherwise
        """
        try:
            memories = await self._backboard.get_memories(assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    # Check if this is an opportunity and matches the ID
                    if data.get("id") == opportunity_id and data.get("stage") and "confidence" in data:
                        return Opportunity.model_validate(data)
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass
        return None

    async def list_opportunities(
        self,
        assistant_id: str,
        active_only: bool = False,
    ) -> list[Opportunity]:
        """List opportunities for a customer.

        Args:
            assistant_id: Customer assistant ID
            active_only: If True, only return non-closed opportunities

        Returns:
            List of Opportunity objects
        """
        opportunities = []
        try:
            memories = await self._backboard.get_memories(assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    # Check if this is an opportunity by looking for opportunity-specific fields
                    if data.get("customer_id") and data.get("stage") and "confidence" in data:
                        opp = Opportunity.model_validate(data)

                        if active_only and opp.stage in [
                            OpportunityStage.CLOSED_WON,
                            OpportunityStage.CLOSED_LOST,
                        ]:
                            continue

                        opportunities.append(opp)
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass
        return opportunities

    async def update_opportunity(
        self,
        assistant_id: str,
        opportunity_id: str,
        data: OpportunityUpdate,
    ) -> Opportunity | None:
        """Update an opportunity.

        Args:
            assistant_id: Customer assistant ID
            opportunity_id: Opportunity ID to update
            data: Update data

        Returns:
            Updated Opportunity or None if not found
        """
        try:
            memories = await self._backboard.get_memories(assistant_id)
            for memory in memories.memories:
                try:
                    opp_data = json.loads(memory.content)
                    # Check if this is an opportunity and matches the ID
                    if opp_data.get("id") == opportunity_id and opp_data.get("stage") and "confidence" in opp_data:

                        # Apply updates (only non-None values)
                        update_dict = data.model_dump(exclude_none=True)
                        opp_data.update(update_dict)
                        opp_data["updated_at"] = datetime.utcnow().isoformat()

                        updated_opp = Opportunity.model_validate(opp_data)
                        await self._backboard.update_memory(
                            assistant_id=assistant_id,
                            memory_id=memory.id,
                            content=updated_opp.to_memory_content(),
                        )
                        return updated_opp
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass
        return None

    async def delete_opportunity(
        self,
        assistant_id: str,
        opportunity_id: str,
    ) -> bool:
        """Delete an opportunity.

        Args:
            assistant_id: Customer assistant ID
            opportunity_id: Opportunity ID to delete

        Returns:
            True if deleted, False if not found
        """
        try:
            memories = await self._backboard.get_memories(assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    # Check if this is an opportunity and matches the ID
                    if data.get("id") == opportunity_id and data.get("stage") and "confidence" in data:
                        await self._backboard.delete_memory(
                            assistant_id=assistant_id,
                            memory_id=memory.id,
                        )
                        return True
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass
        return False

    async def update_opportunity_from_meeting(
        self,
        assistant_id: str,
        opportunity_id: str,
        stage_signal: str | None = None,
        confidence_delta: int = 0,
        competitors: list[str] | None = None,
    ) -> Opportunity | None:
        """Update an opportunity based on meeting signals.

        Args:
            assistant_id: Customer assistant ID
            opportunity_id: Opportunity ID to update
            stage_signal: Suggested stage from meeting
            confidence_delta: Confidence change (-50 to +50)
            competitors: Competitors mentioned

        Returns:
            Updated Opportunity or None
        """
        opp = await self.get_opportunity(assistant_id, opportunity_id)
        if not opp:
            return None

        updates = OpportunityUpdate()

        # Update stage if signaled
        if stage_signal:
            stage_map = {
                "discovery": OpportunityStage.DISCOVERY,
                "qualification": OpportunityStage.QUALIFICATION,
                "proposal": OpportunityStage.PROPOSAL,
                "negotiation": OpportunityStage.NEGOTIATION,
            }
            if stage_signal.lower() in stage_map:
                updates.stage = stage_map[stage_signal.lower()]

        # Adjust confidence
        if confidence_delta:
            new_confidence = max(0, min(100, opp.confidence + confidence_delta))
            updates.confidence = new_confidence

        # Add competitors
        if competitors:
            existing = set(opp.competitors)
            existing.update(competitors)
            updates.competitors = list(existing)

        return await self.update_opportunity(assistant_id, opportunity_id, updates)

    # Activity operations
    async def create_activity(
        self,
        assistant_id: str,
        customer_id: str,
        thread_id: str,
        activity_type: ActivityType,
        summary: str,
        activity_date: datetime | None = None,
        opportunity_id: str | None = None,
        participants: list[str] | None = None,
        action_items: list[dict[str, Any]] | None = None,
    ) -> Activity:
        """Create a new activity.

        Args:
            assistant_id: Customer assistant ID
            customer_id: Customer ID
            thread_id: Associated thread ID
            activity_type: Type of activity
            summary: Activity summary
            activity_date: When the activity occurred
            opportunity_id: Optional related opportunity
            participants: List of participant names
            action_items: List of action item dicts

        Returns:
            Created Activity object
        """
        # Convert action item dicts to objects
        action_item_objs = []
        if action_items:
            for ai in action_items:
                action_item_objs.append(
                    ActionItem(
                        id=str(uuid.uuid4()),
                        description=ai.get("description", ""),
                        owner=ai.get("owner"),
                        due_date=ai.get("due_date"),
                        is_completed=ai.get("is_completed", False),
                    )
                )

        activity = Activity(
            id=str(uuid.uuid4()),
            customer_id=customer_id,
            opportunity_id=opportunity_id,
            thread_id=thread_id,
            activity_type=activity_type,
            date=activity_date or datetime.utcnow(),
            summary=summary,
            participants=participants or [],
            action_items=action_item_objs,
            created_at=datetime.utcnow(),
        )

        # Store activity in memory (metadata excluded - can cause API issues)
        await self._backboard.add_memory(
            assistant_id=assistant_id,
            content=activity.to_memory_content(),
        )

        return activity

    async def get_activity(
        self,
        assistant_id: str,
        activity_id: str,
    ) -> Activity | None:
        """Get an activity by ID.

        Args:
            assistant_id: Customer assistant ID
            activity_id: Activity ID to find

        Returns:
            Activity if found, None otherwise
        """
        try:
            memories = await self._backboard.get_memories(assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    # Check if this is an activity and matches the ID
                    if data.get("id") == activity_id and data.get("thread_id") and data.get("activity_type"):
                        return Activity.model_validate(data)
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass
        return None

    async def list_activities(
        self,
        assistant_id: str,
        limit: int = 50,
        activity_type: ActivityType | None = None,
    ) -> list[Activity]:
        """List activities for a customer.

        Args:
            assistant_id: Customer assistant ID
            limit: Maximum number to return
            activity_type: Optional filter by type

        Returns:
            List of Activity objects, sorted by date descending
        """
        activities = []
        try:
            memories = await self._backboard.get_memories(assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    # Check if this is an activity by looking for activity-specific fields
                    if data.get("thread_id") and data.get("activity_type") and data.get("summary"):
                        if activity_type and data.get("activity_type") != activity_type.value:
                            continue

                        activities.append(Activity.model_validate(data))
                except (json.JSONDecodeError, ValueError):
                    continue

            # Sort by date descending
            activities.sort(key=lambda a: a.date, reverse=True)
        except Exception:
            pass

        return activities[:limit]

    async def get_pending_action_items(
        self,
        assistant_id: str,
    ) -> list[dict[str, Any]]:
        """Get all pending action items across activities.

        Args:
            assistant_id: Customer assistant ID

        Returns:
            List of action items with their activity context
        """
        pending = []
        activities = await self.list_activities(assistant_id, limit=100)

        for activity in activities:
            for action_item in activity.action_items:
                if not action_item.is_completed:
                    pending.append({
                        "action_item": action_item.model_dump(),
                        "activity_id": activity.id,
                        "activity_date": activity.date.isoformat(),
                        "activity_summary": activity.summary,
                    })

        return pending

    # PromotedActionItem operations
    async def create_promoted_action_item(
        self,
        assistant_id: str,
        customer_id: str,
        activity_id: str,
        thread_id: str,
        description: str,
        owner: str | None = None,
        due_date: date | None = None,
        source_excerpt: str | None = None,
    ) -> PromotedActionItem:
        """Create a new promoted action item.

        Args:
            assistant_id: Customer assistant ID
            customer_id: Customer ID
            activity_id: Source activity ID
            thread_id: Source thread ID
            description: What needs to be done
            owner: Who is responsible
            due_date: When it's due
            source_excerpt: Transcript excerpt that generated this

        Returns:
            Created PromotedActionItem object
        """
        action_item = PromotedActionItem(
            id=str(uuid.uuid4()),
            customer_id=customer_id,
            activity_id=activity_id,
            thread_id=thread_id,
            description=description,
            owner=owner,
            due_date=due_date,
            is_completed=False,
            is_dismissed=False,
            source_excerpt=source_excerpt,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        await self._backboard.add_memory(
            assistant_id=assistant_id,
            content=action_item.to_memory_content(),
        )

        return action_item

    async def get_promoted_action_item(
        self,
        assistant_id: str,
        action_item_id: str,
    ) -> PromotedActionItem | None:
        """Get a promoted action item by ID.

        Args:
            assistant_id: Customer assistant ID
            action_item_id: Action item ID to find

        Returns:
            PromotedActionItem if found, None otherwise
        """
        try:
            memories = await self._backboard.get_memories(assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    # Check if this is a promoted action item and matches the ID
                    if (
                        data.get("id") == action_item_id
                        and data.get("activity_id")
                        and "source_excerpt" in data
                    ):
                        return PromotedActionItem.model_validate(data)
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass
        return None

    async def list_promoted_action_items(
        self,
        assistant_id: str,
        include_dismissed: bool = False,
        include_completed: bool = True,
        limit: int = 50,
    ) -> list[PromotedActionItem]:
        """List promoted action items for a customer.

        Args:
            assistant_id: Customer assistant ID
            include_dismissed: If True, include dismissed items
            include_completed: If True, include completed items
            limit: Maximum number to return

        Returns:
            List of PromotedActionItem objects, sorted by created_at descending
        """
        items = []
        try:
            memories = await self._backboard.get_memories(assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    # Check if this is a promoted action item
                    if (
                        data.get("activity_id")
                        and data.get("thread_id")
                        and "source_excerpt" in data
                        and "is_dismissed" in data
                    ):
                        item = PromotedActionItem.model_validate(data)

                        # Apply filters
                        if not include_dismissed and item.is_dismissed:
                            continue
                        if not include_completed and item.is_completed:
                            continue

                        items.append(item)
                except (json.JSONDecodeError, ValueError):
                    continue

            # Sort by created_at descending
            items.sort(key=lambda i: i.created_at, reverse=True)
        except Exception:
            pass

        return items[:limit]

    async def update_promoted_action_item(
        self,
        assistant_id: str,
        action_item_id: str,
        data: PromotedActionItemUpdate,
    ) -> PromotedActionItem | None:
        """Update a promoted action item.

        Args:
            assistant_id: Customer assistant ID
            action_item_id: Action item ID to update
            data: Update data

        Returns:
            Updated PromotedActionItem or None if not found
        """
        try:
            memories = await self._backboard.get_memories(assistant_id)
            for memory in memories.memories:
                try:
                    item_data = json.loads(memory.content)
                    # Check if this is a promoted action item and matches the ID
                    if (
                        item_data.get("id") == action_item_id
                        and item_data.get("activity_id")
                        and "source_excerpt" in item_data
                    ):
                        # Apply updates (only non-None values)
                        update_dict = data.model_dump(exclude_none=True)
                        item_data.update(update_dict)
                        item_data["updated_at"] = datetime.utcnow().isoformat()

                        updated_item = PromotedActionItem.model_validate(item_data)
                        await self._backboard.update_memory(
                            assistant_id=assistant_id,
                            memory_id=memory.id,
                            content=updated_item.to_memory_content(),
                        )
                        return updated_item
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass
        return None

    async def dismiss_promoted_action_item(
        self,
        assistant_id: str,
        action_item_id: str,
    ) -> PromotedActionItem | None:
        """Dismiss (soft delete) a promoted action item.

        Args:
            assistant_id: Customer assistant ID
            action_item_id: Action item ID to dismiss

        Returns:
            Dismissed PromotedActionItem or None if not found
        """
        try:
            memories = await self._backboard.get_memories(assistant_id)
            for memory in memories.memories:
                try:
                    item_data = json.loads(memory.content)
                    # Check if this is a promoted action item and matches the ID
                    if (
                        item_data.get("id") == action_item_id
                        and item_data.get("activity_id")
                        and "source_excerpt" in item_data
                    ):
                        item_data["is_dismissed"] = True
                        item_data["updated_at"] = datetime.utcnow().isoformat()

                        updated_item = PromotedActionItem.model_validate(item_data)
                        await self._backboard.update_memory(
                            assistant_id=assistant_id,
                            memory_id=memory.id,
                            content=updated_item.to_memory_content(),
                        )
                        return updated_item
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass
        return None

    async def backfill_promoted_action_items(
        self,
        assistant_id: str,
        customer_id: str,
    ) -> int:
        """Backfill promoted action items from existing activities.

        This migrates embedded action items from Activity objects to
        standalone PromotedActionItem records.

        Args:
            assistant_id: Customer assistant ID
            customer_id: Customer ID

        Returns:
            Number of action items backfilled
        """
        count = 0
        try:
            # Get existing promoted action item descriptions to avoid duplicates
            existing_items = await self.list_promoted_action_items(
                assistant_id, include_dismissed=True, include_completed=True, limit=500
            )
            existing_descriptions = {item.description.lower() for item in existing_items}

            # Get all activities
            activities = await self.list_activities(assistant_id, limit=500)

            for activity in activities:
                for action_item in activity.action_items:
                    # Skip if already exists (by description match)
                    if action_item.description.lower() in existing_descriptions:
                        continue

                    # Create promoted action item
                    promoted = PromotedActionItem(
                        id=str(uuid.uuid4()),
                        customer_id=customer_id,
                        activity_id=activity.id,
                        thread_id=activity.thread_id,
                        description=action_item.description,
                        owner=action_item.owner,
                        due_date=action_item.due_date,
                        is_completed=action_item.is_completed,
                        is_dismissed=False,
                        source_excerpt=None,  # Not available for old items
                        created_at=activity.date,
                        updated_at=datetime.utcnow(),
                    )

                    await self._backboard.add_memory(
                        assistant_id=assistant_id,
                        content=promoted.to_memory_content(),
                    )

                    existing_descriptions.add(action_item.description.lower())
                    count += 1

        except Exception:
            pass

        return count


def get_crm_service(backboard: BackboardService) -> CRMService:
    """Get a CRMService instance.

    Args:
        backboard: BackboardService instance to use

    Returns:
        CRMService instance
    """
    return CRMService(backboard)
