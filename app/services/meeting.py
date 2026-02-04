"""Meeting service for processing transcripts and managing meeting threads."""

import json
import re
import uuid
from datetime import datetime
from typing import Any

from app.prompts.extraction import get_meeting_notes_prompt
from app.schemas.crm import Activity, ActionItem, PromotedActionItem
from app.schemas.enums import ActivityType
from app.schemas.meeting import MeetingNotes, StakeholderMention, TranscriptMetadata
from app.services.backboard import BackboardService


class MeetingService:
    """Service for managing meeting threads and transcript processing."""

    def __init__(self, backboard: BackboardService):
        """Initialize the meeting service.

        Args:
            backboard: BackboardService instance
        """
        self._backboard = backboard

    async def create_meeting_thread(
        self,
        customer_assistant_id: str,
        meeting_type: str = "meeting",
        meeting_date: datetime | None = None,
        participants: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new thread for a meeting under a customer assistant.

        Args:
            customer_assistant_id: The customer's assistant ID
            meeting_type: Type of meeting (meeting, call, demo, etc.)
            meeting_date: When the meeting occurred
            participants: List of participant names

        Returns:
            Thread info including thread_id
        """
        thread = await self._backboard.create_thread(customer_assistant_id)

        return {
            "thread_id": thread.thread_id,
            "assistant_id": customer_assistant_id,
            "meeting_type": meeting_type,
            "meeting_date": (meeting_date or datetime.utcnow()).isoformat(),
            "participants": participants or [],
        }

    async def process_transcript(
        self,
        thread_id: str,
        customer_assistant_id: str,
        customer_id: str,
        company_name: str,
        transcript: str,
        metadata: TranscriptMetadata | None = None,
        known_contacts: list[str] | None = None,
        current_stage: str | None = None,
        previous_context: str | None = None,
    ) -> tuple[MeetingNotes, Activity]:
        """Process a transcript and extract structured meeting notes.

        Args:
            thread_id: The meeting thread ID
            customer_assistant_id: The customer's assistant ID
            customer_id: The customer's ID
            company_name: The customer's company name
            transcript: The meeting transcript text
            metadata: Optional transcript metadata
            known_contacts: List of known contact names
            current_stage: Current opportunity stage
            previous_context: Summary of previous meetings

        Returns:
            Tuple of (MeetingNotes, Activity) objects
        """
        # Build the extraction prompt
        prompt = get_meeting_notes_prompt(
            transcript=transcript,
            company_name=company_name,
            known_contacts=known_contacts,
            current_stage=current_stage,
            previous_context=previous_context,
        )

        # Send to the customer assistant for processing
        response = await self._backboard.send_message(
            thread_id=thread_id,
            content=prompt,
            memory="off",  # Disable memory due to API issues
        )

        # Get content from response (handle different response formats)
        content = ""
        if hasattr(response, "content"):
            content = response.content or ""
        elif isinstance(response, dict):
            content = response.get("content", "")

        # Parse the response into MeetingNotes
        notes = self._parse_meeting_notes(content)

        # Create Activity record
        meeting_date = metadata.call_date if metadata else datetime.utcnow()
        meeting_type = metadata.call_type if metadata else "meeting"

        activity = Activity(
            id=str(uuid.uuid4()),
            customer_id=customer_id,
            opportunity_id=metadata.opportunity_id if metadata else None,
            thread_id=thread_id,
            activity_type=ActivityType(meeting_type) if meeting_type in ["meeting", "call", "email", "task", "note"] else ActivityType.MEETING,
            date=meeting_date or datetime.utcnow(),
            summary=notes.summary,
            participants=metadata.contact_hints if metadata else [],
            action_items=[
                ActionItem(
                    id=str(uuid.uuid4()),
                    description=ai.description,
                    owner=ai.owner,
                    due_date=None,  # Would need date parsing
                    is_completed=False,
                )
                for ai in notes.action_items
            ],
            created_at=datetime.utcnow(),
        )

        # Store meeting summary in memory (metadata excluded - can cause API issues)
        meeting_summary = {
            "type": "meeting_summary",
            "thread_id": thread_id,
            "date": activity.date.isoformat(),
            "summary": notes.summary,
            "products_discussed": notes.products_discussed,
            "sales_value": notes.sales_value,
            "pain_points": notes.pain_points,
            "labels": notes.labels,
            "sentiment": notes.sentiment,
        }
        await self._backboard.add_memory(
            assistant_id=customer_assistant_id,
            content=json.dumps(meeting_summary),
        )

        # Store Activity object in memory
        await self._backboard.add_memory(
            assistant_id=customer_assistant_id,
            content=activity.to_memory_content(),
        )

        # Create PromotedActionItem objects for each action item
        for ai in notes.action_items:
            promoted_item = PromotedActionItem(
                id=str(uuid.uuid4()),
                customer_id=customer_id,
                activity_id=activity.id,
                thread_id=thread_id,
                description=ai.description,
                owner=ai.owner,
                due_date=None,  # Would need date parsing from ai.due_date string
                is_completed=False,
                is_dismissed=False,
                source_excerpt=ai.source_excerpt,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            await self._backboard.add_memory(
                assistant_id=customer_assistant_id,
                content=promoted_item.to_memory_content(),
            )

        return notes, activity

    def _parse_meeting_notes(self, content: str) -> MeetingNotes:
        """Parse meeting notes from LLM response.

        Args:
            content: The LLM response content

        Returns:
            Parsed MeetingNotes object
        """
        try:
            # Find JSON in response
            json_match = re.search(r"\{[\s\S]*\}", content) if content else None
            if json_match:
                data = json.loads(json_match.group())
                sales_value = self._normalize_sales_value(data.get("sales_value"))

                # Parse stakeholders
                stakeholders = []
                for s in data.get("stakeholders", []):
                    if isinstance(s, dict):
                        stakeholders.append(
                            StakeholderMention(
                                name=s.get("name", "Unknown"),
                                role=s.get("role"),
                                email=s.get("email"),
                                sentiment=s.get("sentiment"),
                                context=s.get("context"),
                                preferred_contact_method=self._normalize_contact_method(
                                    s.get("preferred_contact_method")
                                ),
                            )
                        )

                # Parse action items
                from app.schemas.meeting import ActionItem as MeetingActionItem

                action_items = []
                for ai in data.get("action_items", []):
                    if isinstance(ai, dict):
                        action_items.append(
                            MeetingActionItem(
                                description=ai.get("description", ""),
                                owner=ai.get("owner"),
                                due_date=ai.get("due_date"),
                                priority=ai.get("priority", "medium"),
                                source_excerpt=ai.get("source_excerpt"),
                            )
                        )

                return MeetingNotes(
                    summary=data.get("summary", "No summary available"),
                    products_discussed=data.get("products_discussed", []) or [],
                    sales_value=sales_value,
                    pain_points=data.get("pain_points", []),
                    needs=data.get("needs", []),
                    objections=data.get("objections", []),
                    competitors_mentioned=data.get("competitors_mentioned", []),
                    requirements=data.get("requirements", []),
                    next_steps=data.get("next_steps", []),
                    risks=data.get("risks", []),
                    stakeholders=stakeholders,
                    action_items=action_items,
                    labels=data.get("labels", []),
                    sentiment=data.get("sentiment", "neutral"),
                    deal_stage_signal=data.get("deal_stage_signal"),
                    confidence_delta=data.get("confidence_delta", 0),
                )
        except (json.JSONDecodeError, AttributeError, KeyError):
            pass

        # Return minimal notes on parse failure
        return MeetingNotes(
            summary=content[:500] if content else "Failed to parse meeting notes",
            sentiment="neutral",
        )

    def _normalize_sales_value(self, raw_value: Any) -> float | None:
        """Normalize a sales value to a float if possible."""
        if raw_value is None:
            return None
        if isinstance(raw_value, (int, float)):
            return float(raw_value)
        if not isinstance(raw_value, str):
            return None

        cleaned = raw_value.strip().lower().replace(",", "")
        match = re.search(r"(\d+(?:\.\d+)?)\s*([kmb])?", cleaned)
        if not match:
            return None

        value = float(match.group(1))
        multiplier = match.group(2)
        if multiplier == "k":
            value *= 1_000
        elif multiplier == "m":
            value *= 1_000_000
        elif multiplier == "b":
            value *= 1_000_000_000
        return value

    def _normalize_contact_method(self, raw_method: Any) -> "ContactMethod | None":
        """Normalize preferred contact method values."""
        from app.schemas.enums import ContactMethod

        if isinstance(raw_method, ContactMethod):
            return raw_method
        if not raw_method:
            return None
        if not isinstance(raw_method, str):
            return None

        normalized = raw_method.strip().lower()
        method_map = {
            "email": ContactMethod.EMAIL,
            "text": ContactMethod.TEXT,
            "sms": ContactMethod.TEXT,
            "call": ContactMethod.CALL,
            "phone": ContactMethod.CALL,
            "whatsapp": ContactMethod.WHATSAPP,
        }
        return method_map.get(normalized)

    async def get_meeting(
        self,
        thread_id: str,
    ) -> dict[str, Any] | None:
        """Get meeting details including messages.

        Args:
            thread_id: The meeting thread ID

        Returns:
            Meeting info with messages or None if not found
        """
        try:
            thread = await self._backboard.get_thread(thread_id)
            return {
                "thread_id": thread.thread_id,
                "messages": [
                    {
                        "role": msg.role,
                        "content": msg.content,
                    }
                    for msg in getattr(thread, "messages", [])
                ],
            }
        except Exception:
            return None

    async def get_customer_meetings(
        self,
        customer_assistant_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get all meetings for a customer.

        Args:
            customer_assistant_id: The customer's assistant ID
            limit: Maximum number of meetings to return

        Returns:
            List of meeting summaries
        """
        meetings = []
        try:
            memories = await self._backboard.get_memories(customer_assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    # Check if this is a meeting summary by looking for specific fields
                    if data.get("type") == "meeting_summary":
                        # Get memory_id safely - could be memory_id or id attribute
                        mem_id = getattr(memory, "memory_id", None) or getattr(memory, "id", None)
                        meetings.append({
                            "thread_id": data.get("thread_id"),
                            "date": data.get("date"),
                            "summary": data.get("summary"),
                            "products_discussed": data.get("products_discussed", []),
                            "sales_value": data.get("sales_value"),
                            "labels": data.get("labels", []),
                            "sentiment": data.get("sentiment"),
                            "memory_id": str(mem_id) if mem_id else None,
                        })
                except (json.JSONDecodeError, ValueError):
                    continue

            # Sort by date descending
            meetings.sort(key=lambda m: m.get("date", ""), reverse=True)
        except Exception:
            pass

        return meetings[:limit]

    async def delete_meeting(
        self,
        customer_assistant_id: str,
        thread_id: str,
    ) -> bool:
        """Delete a meeting by its thread ID.

        Args:
            customer_assistant_id: The customer's assistant ID
            thread_id: The meeting's thread ID

        Returns:
            True if deleted, False if not found
        """
        try:
            memories = await self._backboard.get_memories(customer_assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    if data.get("type") == "meeting_summary" and data.get("thread_id") == thread_id:
                        mem_id = getattr(memory, "memory_id", None) or getattr(memory, "id", None)
                        if mem_id:
                            await self._backboard.delete_memory(
                                customer_assistant_id,
                                str(mem_id),
                            )
                            return True
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass
        return False

    async def update_meeting_labels(
        self,
        customer_assistant_id: str,
        thread_id: str,
        labels: list[str],
    ) -> dict[str, Any] | None:
        """Update labels for a meeting.

        Args:
            customer_assistant_id: The customer's assistant ID
            thread_id: The meeting's thread ID
            labels: New list of labels

        Returns:
            Updated meeting data or None if not found
        """
        try:
            memories = await self._backboard.get_memories(customer_assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    if data.get("type") == "meeting_summary" and data.get("thread_id") == thread_id:
                        mem_id = getattr(memory, "memory_id", None) or getattr(memory, "id", None)
                        if not mem_id:
                            continue
                        # Update labels
                        data["labels"] = labels
                        # Update the memory with new content
                        await self._backboard.update_memory(
                            customer_assistant_id,
                            str(mem_id),
                            json.dumps(data),
                        )
                        return {
                            "thread_id": data.get("thread_id"),
                            "date": data.get("date"),
                            "summary": data.get("summary"),
                            "products_discussed": data.get("products_discussed", []),
                            "sales_value": data.get("sales_value"),
                            "labels": data.get("labels", []),
                            "sentiment": data.get("sentiment"),
                        }
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass
        return None

    async def rename_product_across_meetings(
        self,
        customer_assistant_id: str,
        old_name: str,
        new_name: str,
    ) -> list[str]:
        """Rename a product across all meeting summaries for a customer.

        Args:
            customer_assistant_id: The customer's assistant ID
            old_name: The current product name
            new_name: The new product name

        Returns:
            Updated list of all unique products
        """
        all_products = set()
        try:
            memories = await self._backboard.get_memories(customer_assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    if data.get("type") == "meeting_summary":
                        products = data.get("products_discussed", []) or []
                        updated = False
                        new_products = []
                        for product in products:
                            if product == old_name:
                                new_products.append(new_name)
                                updated = True
                            else:
                                new_products.append(product)

                        if updated:
                            mem_id = getattr(memory, "memory_id", None) or getattr(memory, "id", None)
                            if mem_id:
                                data["products_discussed"] = new_products
                                await self._backboard.update_memory(
                                    customer_assistant_id,
                                    str(mem_id),
                                    json.dumps(data),
                                )

                        all_products.update(new_products)
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass

        return sorted(all_products)

    async def delete_product_across_meetings(
        self,
        customer_assistant_id: str,
        product_name: str,
    ) -> list[str]:
        """Delete a product from all meeting summaries for a customer.

        Args:
            customer_assistant_id: The customer's assistant ID
            product_name: The product name to remove

        Returns:
            Updated list of all unique products
        """
        all_products = set()
        try:
            memories = await self._backboard.get_memories(customer_assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    if data.get("type") == "meeting_summary":
                        products = data.get("products_discussed", []) or []
                        if product_name in products:
                            new_products = [p for p in products if p != product_name]
                            mem_id = getattr(memory, "memory_id", None) or getattr(memory, "id", None)
                            if mem_id:
                                data["products_discussed"] = new_products
                                await self._backboard.update_memory(
                                    customer_assistant_id,
                                    str(mem_id),
                                    json.dumps(data),
                                )
                            all_products.update(new_products)
                        else:
                            all_products.update(products)
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass

        return sorted(all_products)

    async def get_all_products(
        self,
        customer_assistant_id: str,
    ) -> list[str]:
        """Get all unique products discussed across all meetings.

        Args:
            customer_assistant_id: The customer's assistant ID

        Returns:
            Sorted list of unique product names
        """
        all_products = set()
        try:
            memories = await self._backboard.get_memories(customer_assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    if data.get("type") == "meeting_summary":
                        products = data.get("products_discussed", []) or []
                        all_products.update(products)
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass

        return sorted(all_products)


def get_meeting_service(backboard: BackboardService) -> MeetingService:
    """Get a MeetingService instance.

    Args:
        backboard: BackboardService instance to use

    Returns:
        MeetingService instance
    """
    return MeetingService(backboard)
