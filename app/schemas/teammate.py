"""Teammate detection and shared meeting schemas for CloserNotes."""

from datetime import datetime

from pydantic import BaseModel, Field


class DetectedTeammate(BaseModel):
    """A teammate detected during transcript ingestion."""

    user_id: str = Field(..., description="Matched user's ID")
    user_name: str = Field(..., description="Matched user's display name")
    user_email: str = Field(..., description="Matched user's email")
    extracted_name: str = Field(
        ..., description="Name as it appeared in the transcript"
    )
    confidence: float = Field(
        1.0,
        ge=0.0,
        le=1.0,
        description="Match confidence (1.0 = exact, <1.0 = fuzzy first-name match)",
    )


class UserMeetingVersion(BaseModel):
    """One user's view of a shared meeting."""

    user_id: str = Field(..., description="User who ingested this version")
    thread_id: str = Field(..., description="Meeting thread ID for this version")
    activity_id: str = Field(..., description="Activity record ID")
    summary: str = Field("", description="Meeting summary from this user's notes")
    next_steps: list[str] = Field(
        default_factory=list, description="Next steps extracted"
    )
    action_items: list[dict] = Field(
        default_factory=list, description="Action items extracted"
    )
    deal_stage_signal: str | None = Field(
        None, description="Deal stage signal from this user"
    )
    sales_value: float | None = Field(
        None, description="Sales value mentioned by this user"
    )
    ingested_at: datetime = Field(default_factory=datetime.utcnow)


class Discrepancy(BaseModel):
    """A flagged difference between teammate meeting notes."""

    field: str = Field(
        ..., description="Which field differs (e.g. next_steps, deal_stage_signal)"
    )
    description: str = Field(..., description="Human-readable description")
    user_a_value: str = Field(..., description="Value from user A")
    user_b_value: str = Field(..., description="Value from user B")


class SharedMeeting(BaseModel):
    """A meeting shared between teammates, stored in Backboard."""

    id: str = Field(..., description="Unique shared meeting identifier")
    customer_assistant_id: str = Field(
        ..., description="Customer assistant this meeting belongs to"
    )
    customer_name: str = Field(..., description="Customer company name")
    meeting_date: datetime = Field(..., description="When the meeting occurred")
    user_notes: dict[str, UserMeetingVersion] = Field(
        default_factory=dict,
        description="Meeting notes keyed by user_id",
    )
    discrepancies: list[Discrepancy] = Field(
        default_factory=list, description="Flagged discrepancies between user notes"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_memory_content(self) -> str:
        """Serialize to memory-friendly JSON."""
        return self.model_dump_json()
