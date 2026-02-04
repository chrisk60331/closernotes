"""Meeting and transcript analysis schemas for CloserNotes."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.enums import ContactMethod


class StakeholderMention(BaseModel):
    """A stakeholder mentioned during a meeting."""

    name: str = Field(..., description="Person's name")
    role: str | None = Field(None, description="Their role/title if mentioned")
    company: str | None = Field(None, description="Their company if mentioned")
    email: str | None = Field(None, description="Email address if mentioned")
    sentiment: str | None = Field(
        None, description="Inferred sentiment: positive, neutral, negative, unknown"
    )
    context: str | None = Field(None, description="Context of how they were mentioned")
    preferred_contact_method: ContactMethod | None = Field(
        None, description="Preferred contact method if mentioned: email, text, call, whatsapp"
    )


class ActionItem(BaseModel):
    """An action item extracted from meeting notes."""

    description: str = Field(..., description="What needs to be done")
    owner: str | None = Field(None, description="Who should do it (us or them)")
    due_date: str | None = Field(None, description="When it's due if mentioned")
    priority: str = Field("medium", description="Priority: high, medium, low")
    source_excerpt: str | None = Field(
        None, description="Verbatim quote from transcript that generated this action"
    )


class MeetingNotes(BaseModel):
    """Structured notes extracted from a meeting transcript."""

    summary: str = Field(..., description="2-3 sentence executive summary")
    products_discussed: list[str] = Field(
        default_factory=list, description="Products or solutions discussed"
    )
    sales_value: float | None = Field(
        None, description="Estimated sales value discussed in the meeting"
    )
    pain_points: list[str] = Field(
        default_factory=list, description="Customer pain points mentioned"
    )
    needs: list[str] = Field(
        default_factory=list, description="Explicit needs or requirements stated"
    )
    objections: list[str] = Field(
        default_factory=list, description="Objections or concerns raised"
    )
    competitors_mentioned: list[str] = Field(
        default_factory=list, description="Competitor names mentioned"
    )
    requirements: list[str] = Field(
        default_factory=list, description="Technical or business requirements"
    )
    next_steps: list[str] = Field(
        default_factory=list, description="Agreed next steps"
    )
    risks: list[str] = Field(
        default_factory=list, description="Deal risks or red flags identified"
    )
    stakeholders: list[StakeholderMention] = Field(
        default_factory=list, description="People mentioned in the meeting"
    )
    action_items: list[ActionItem] = Field(
        default_factory=list, description="Action items for follow-up"
    )
    labels: list[str] = Field(
        default_factory=list, description="Natural language labels for categorization"
    )
    sentiment: str = Field(
        "neutral", description="Overall meeting sentiment: positive, neutral, negative"
    )
    deal_stage_signal: str | None = Field(
        None, description="Inferred deal stage based on conversation"
    )
    confidence_delta: int = Field(
        0, ge=-50, le=50, description="Suggested change to deal confidence (-50 to +50)"
    )


class TranscriptMetadata(BaseModel):
    """Metadata provided with a transcript for ingestion."""

    caller_email: str | None = Field(None, description="Email of the person who recorded")
    company_hint: str | None = Field(None, description="Hint about customer company name")
    contact_hints: list[str] = Field(
        default_factory=list, description="Names of people on the call"
    )
    call_date: datetime | None = Field(None, description="When the call occurred")
    call_type: str = Field("meeting", description="Type: meeting, call, demo, etc.")
    opportunity_id: str | None = Field(None, description="Existing opportunity to link to")


class IngestRequest(BaseModel):
    """Request payload for transcript ingestion."""

    transcript: str = Field(..., min_length=10, description="The meeting transcript text")
    metadata: TranscriptMetadata = Field(
        default_factory=TranscriptMetadata, description="Optional metadata"
    )


class IngestResponse(BaseModel):
    """Response from transcript ingestion."""

    meeting_id: str = Field(..., description="ID of the created meeting/thread")
    customer_id: str = Field(..., description="ID of the associated customer")
    assistant_id: str = Field(..., description="Assistant ID for routing to customer page")
    customer_name: str = Field(..., description="Name of the customer company")
    is_new_customer: bool = Field(..., description="Whether this is a new customer")
    notes: MeetingNotes = Field(..., description="Extracted meeting notes")
    crm_updates: dict = Field(
        default_factory=dict, description="Summary of CRM objects created/updated"
    )


class EntityExtraction(BaseModel):
    """Entities extracted from a transcript for routing."""

    company_name: str | None = Field(None, description="Primary company name detected")
    company_domain: str | None = Field(None, description="Company domain if mentioned")
    contacts: list[StakeholderMention] = Field(
        default_factory=list, description="People detected in the transcript"
    )
    signals: list[str] = Field(
        default_factory=list, description="Key signals or topics detected"
    )
    confidence: float = Field(
        0.5, ge=0.0, le=1.0, description="Confidence in extraction accuracy"
    )


class FollowupEmail(BaseModel):
    """A generated follow-up email draft."""

    customer_id: str = Field(..., description="Target customer ID")
    customer_name: str = Field(..., description="Customer company name")
    contact_name: str | None = Field(None, description="Recipient name if known")
    contact_email: str | None = Field(None, description="Recipient email if known")
    subject: str = Field(..., description="Email subject line")
    body: str = Field(..., description="Email body content")
    headline_source: str = Field(..., description="The news headline that triggered this")
    relevance_reason: str = Field(
        ..., description="Why this news is relevant to this customer"
    )
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class NewsHeadline(BaseModel):
    """A news headline from Newsboard for follow-up generation."""

    id: str = Field(..., description="Headline ID")
    title: str = Field(..., description="Headline title")
    summary: str | None = Field(None, description="Brief summary")
    source: str | None = Field(None, description="News source")
    url: str | None = Field(None, description="Link to full article")
    tags: list[str] = Field(default_factory=list, description="Topic tags")
    published_at: datetime | None = Field(None, description="Publication date")
