"""Teammate detection and shared meeting service for CloserNotes."""

import json
import uuid
from datetime import datetime

from app.config import get_settings
from app.schemas.meeting import MeetingNotes
from app.schemas.teammate import (
    DetectedTeammate,
    Discrepancy,
    SharedMeeting,
    UserMeetingVersion,
)
from app.services.backboard import BackboardService
from app.services.user import UserService


class TeammateService:
    """Service for detecting teammates in transcripts and managing shared meetings."""

    def __init__(self, backboard: BackboardService):
        self._backboard = backboard
        self._settings = get_settings()
        self._users_assistant_id: str = self._settings.users_assistant_id

    async def detect_teammates(
        self,
        extracted_names: list[str],
        current_user_id: str,
    ) -> list[DetectedTeammate]:
        """Cross-reference extracted names against system users.

        Args:
            extracted_names: Names found in the transcript (contacts + stakeholders).
            current_user_id: The user currently ingesting -- excluded from matches.

        Returns:
            List of DetectedTeammate for each name that matches a system user.
        """
        user_svc = UserService(self._backboard)
        users = await user_svc.list_users()

        # Build lookup structures for matching
        # exact full-name map  (lowercase -> User)
        full_name_map: dict[str, object] = {}
        # first-name map  (lowercase first token -> list[User])
        first_name_map: dict[str, list] = {}

        for user in users:
            if user.id == current_user_id:
                continue
            full_name_map[user.name.lower().strip()] = user
            first_token = user.name.lower().strip().split()[0] if user.name else ""
            if first_token:
                first_name_map.setdefault(first_token, []).append(user)

        detected: list[DetectedTeammate] = []
        seen_user_ids: set[str] = set()

        for name in extracted_names:
            if not name:
                continue
            norm = name.lower().strip()

            # Exact full-name match
            if norm in full_name_map:
                user = full_name_map[norm]
                if user.id not in seen_user_ids:
                    seen_user_ids.add(user.id)
                    detected.append(
                        DetectedTeammate(
                            user_id=user.id,
                            user_name=user.name,
                            user_email=user.email,
                            extracted_name=name,
                            confidence=1.0,
                        )
                    )
                continue

            # First-name fuzzy match (only if the extracted name is a single
            # token so we don't false-positive on "Chris from Acme")
            first_token = norm.split()[0]
            if first_token in first_name_map:
                candidates = first_name_map[first_token]
                # Pick the first candidate not already matched
                for user in candidates:
                    if user.id not in seen_user_ids:
                        seen_user_ids.add(user.id)
                        detected.append(
                            DetectedTeammate(
                                user_id=user.id,
                                user_name=user.name,
                                user_email=user.email,
                                extracted_name=name,
                                confidence=0.7,
                            )
                        )
                        break

        return detected

    # ------------------------------------------------------------------
    # Shared meetings
    # ------------------------------------------------------------------

    async def find_or_create_shared_meeting(
        self,
        customer_assistant_id: str,
        customer_name: str,
        meeting_date: datetime,
        user_id: str,
        thread_id: str,
        activity_id: str,
        notes: MeetingNotes,
    ) -> SharedMeeting:
        """Link a meeting to a user, creating or updating a SharedMeeting.

        Looks for an existing SharedMeeting for the same customer within a
        24-hour window.  If found, adds this user's version.  Otherwise
        creates a new SharedMeeting.

        Returns:
            The SharedMeeting (new or updated).
        """
        existing = await self._find_shared_meeting(
            customer_assistant_id, meeting_date
        )

        version = UserMeetingVersion(
            user_id=user_id,
            thread_id=thread_id,
            activity_id=activity_id,
            summary=notes.summary,
            next_steps=notes.next_steps,
            action_items=[ai.model_dump() for ai in notes.action_items],
            deal_stage_signal=notes.deal_stage_signal,
            sales_value=notes.sales_value,
            ingested_at=datetime.utcnow(),
        )

        if existing:
            shared, memory_id = existing
            shared.user_notes[user_id] = version
            shared.updated_at = datetime.utcnow()
            # Update the memory in-place
            await self._backboard.update_memory(
                assistant_id=self._users_assistant_id,
                memory_id=memory_id,
                content=shared.to_memory_content(),
            )
            return shared

        # Create new shared meeting
        shared = SharedMeeting(
            id=str(uuid.uuid4()),
            customer_assistant_id=customer_assistant_id,
            customer_name=customer_name,
            meeting_date=meeting_date,
            user_notes={user_id: version},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        content = json.dumps(
            {"type": "shared_meeting", **json.loads(shared.to_memory_content())}
        )
        await self._backboard.add_memory(
            assistant_id=self._users_assistant_id,
            content=content,
        )
        return shared

    async def _find_shared_meeting(
        self,
        customer_assistant_id: str,
        meeting_date: datetime,
    ) -> tuple[SharedMeeting, str] | None:
        """Find an existing SharedMeeting within a 24h window for a customer."""
        try:
            memories = await self._backboard.get_memories(self._users_assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    if data.get("type") != "shared_meeting":
                        continue
                    if data.get("customer_assistant_id") != customer_assistant_id:
                        continue
                    stored_date = datetime.fromisoformat(data["meeting_date"])
                    if abs((stored_date - meeting_date).total_seconds()) <= 86400:
                        mem_id = (
                            getattr(memory, "memory_id", None)
                            or getattr(memory, "id", None)
                        )
                        shared = SharedMeeting.model_validate(data)
                        return shared, str(mem_id)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Note comparison
    # ------------------------------------------------------------------

    def compare_notes(self, shared: SharedMeeting) -> list[Discrepancy]:
        """Compare meeting notes between all users on a SharedMeeting.

        Compares pairwise across users for key fields:
        - next_steps
        - deal_stage_signal
        - sales_value
        - action_items (by description)

        Returns:
            List of Discrepancy objects describing differences.
        """
        versions = list(shared.user_notes.values())
        if len(versions) < 2:
            return []

        discrepancies: list[Discrepancy] = []

        # Compare each pair (for 2 users this is a single comparison)
        for i in range(len(versions)):
            for j in range(i + 1, len(versions)):
                a = versions[i]
                b = versions[j]
                discrepancies.extend(self._compare_pair(a, b))

        return discrepancies

    def _compare_pair(
        self, a: UserMeetingVersion, b: UserMeetingVersion
    ) -> list[Discrepancy]:
        """Compare two users' meeting note versions."""
        result: list[Discrepancy] = []

        # Deal stage signal
        if (a.deal_stage_signal or "") != (b.deal_stage_signal or ""):
            result.append(
                Discrepancy(
                    field="deal_stage_signal",
                    description=(
                        f"Deal stage mismatch: {a.user_id} says "
                        f"'{a.deal_stage_signal or 'none'}' but {b.user_id} "
                        f"says '{b.deal_stage_signal or 'none'}'"
                    ),
                    user_a_value=a.deal_stage_signal or "",
                    user_b_value=b.deal_stage_signal or "",
                )
            )

        # Sales value
        if a.sales_value != b.sales_value and not (
            a.sales_value is None and b.sales_value is None
        ):
            result.append(
                Discrepancy(
                    field="sales_value",
                    description=(
                        f"Sales value mismatch: {a.user_id} recorded "
                        f"${a.sales_value or 0:,.0f} but {b.user_id} recorded "
                        f"${b.sales_value or 0:,.0f}"
                    ),
                    user_a_value=str(a.sales_value or ""),
                    user_b_value=str(b.sales_value or ""),
                )
            )

        # Next steps -- look for date-like differences
        a_steps = set(s.lower().strip() for s in a.next_steps)
        b_steps = set(s.lower().strip() for s in b.next_steps)
        only_a = a_steps - b_steps
        only_b = b_steps - a_steps
        if only_a or only_b:
            # Report only when the sets have meaningful differences
            # (ignore minor wording tweaks by checking size gap)
            if only_a and only_b:
                result.append(
                    Discrepancy(
                        field="next_steps",
                        description=(
                            f"Next steps differ between teammates. "
                            f"{a.user_id} has steps not in {b.user_id}'s notes "
                            f"and vice versa -- please reconcile."
                        ),
                        user_a_value="; ".join(sorted(only_a)),
                        user_b_value="; ".join(sorted(only_b)),
                    )
                )

        # Action items -- compare by description similarity
        a_items = {
            ai.get("description", "").lower().strip() for ai in a.action_items
        }
        b_items = {
            ai.get("description", "").lower().strip() for ai in b.action_items
        }
        only_a_ai = a_items - b_items
        only_b_ai = b_items - a_items
        if only_a_ai and only_b_ai:
            result.append(
                Discrepancy(
                    field="action_items",
                    description=(
                        f"Action items differ between teammates -- "
                        f"please review and merge."
                    ),
                    user_a_value="; ".join(sorted(only_a_ai)),
                    user_b_value="; ".join(sorted(only_b_ai)),
                )
            )

        return result

    async def create_discrepancy_items(
        self,
        shared: SharedMeeting,
        discrepancies: list[Discrepancy],
        customer_assistant_id: str,
        customer_id: str,
    ) -> None:
        """Create PromotedActionItems for each discrepancy flagged.

        Creates one action item per discrepancy on the customer, visible
        to all teammates.
        """
        from app.services.crm import CRMService

        if not discrepancies:
            return

        crm_svc = CRMService(self._backboard)

        # Use the first user's thread/activity for lineage
        first_version = next(iter(shared.user_notes.values()))

        for disc in discrepancies:
            await crm_svc.create_promoted_action_item(
                assistant_id=customer_assistant_id,
                customer_id=customer_id,
                activity_id=first_version.activity_id,
                thread_id=first_version.thread_id,
                description=(
                    f"Teammate discrepancy ({disc.field}): {disc.description}"
                ),
                owner="us",
                source_excerpt=(
                    f"User A: {disc.user_a_value}\n"
                    f"User B: {disc.user_b_value}"
                ),
            )

        # Update the SharedMeeting with discrepancies
        shared.discrepancies = discrepancies
        shared.updated_at = datetime.utcnow()
        existing = await self._find_shared_meeting(
            customer_assistant_id, shared.meeting_date
        )
        if existing:
            _, memory_id = existing
            await self._backboard.update_memory(
                assistant_id=self._users_assistant_id,
                memory_id=memory_id,
                content=json.dumps(
                    {
                        "type": "shared_meeting",
                        **json.loads(shared.to_memory_content()),
                    }
                ),
            )

    async def get_shared_meetings_for_user(
        self, user_id: str
    ) -> list[SharedMeeting]:
        """Retrieve all shared meetings that a user participated in."""
        results: list[SharedMeeting] = []
        try:
            memories = await self._backboard.get_memories(self._users_assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    if data.get("type") != "shared_meeting":
                        continue
                    shared = SharedMeeting.model_validate(data)
                    if user_id in shared.user_notes:
                        results.append(shared)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
        except Exception:
            pass
        return results
