"""CRM object schemas for CloserNotes."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.enums import ActivityType, ContactMethod, CustomerSize, LeadSource, OpportunityStage


class Customer(BaseModel):
    """A customer/company in the CRM."""

    id: str = Field(..., description="Unique customer identifier")
    company_name: str = Field(..., description="Company name")
    domain: str | None = Field(None, description="Company website domain")
    industry: str | None = Field(None, description="Industry vertical")
    size: CustomerSize | None = Field(None, description="Company size category")
    assistant_id: str = Field(..., description="Backboard assistant ID for this customer")
    lead_source: LeadSource | None = Field(None, description="How this customer was first sourced")
    lead_source_detail: str | None = Field(None, description="Extra context for lead source (e.g. referrer name, event name)")
    next_followup_date: date | None = Field(None, description="Next suggested follow-up date")
    assigned_user_id: str | None = Field(None, description="Assigned user ID for this customer")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_memory_content(self) -> str:
        """Serialize customer to memory-friendly format."""
        return self.model_dump_json()

    def to_memory_metadata(self) -> dict[str, Any]:
        """Generate memory metadata tags."""
        return {
            "type": "customer",
            "id": self.id,
            "company_name": self.company_name,
        }


class Contact(BaseModel):
    """A contact person at a customer company."""

    id: str = Field(..., description="Unique contact identifier")
    customer_id: str = Field(..., description="Parent customer ID")
    name: str = Field(..., description="Contact full name")
    email: str | None = Field(None, description="Email address")
    phone: str | None = Field(None, description="Phone number")
    role: str | None = Field(None, description="Job title/role")
    linkedin_url: str | None = Field(None, description="LinkedIn profile URL")
    is_champion: bool = Field(False, description="Is this contact our champion?")
    is_decision_maker: bool = Field(False, description="Can this contact make buying decisions?")
    preferred_contact_method: ContactMethod | None = Field(
        None, description="Preferred way to reach this contact"
    )
    notes: str | None = Field(None, description="Additional notes about this contact")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_memory_content(self) -> str:
        """Serialize contact to memory-friendly format."""
        return self.model_dump_json()

    def to_memory_metadata(self) -> dict[str, Any]:
        """Generate memory metadata tags."""
        return {
            "type": "contact",
            "id": self.id,
            "customer_id": self.customer_id,
            "name": self.name,
        }


class Opportunity(BaseModel):
    """A sales opportunity with a customer."""

    id: str = Field(..., description="Unique opportunity identifier")
    customer_id: str = Field(..., description="Parent customer ID")
    name: str = Field(..., description="Opportunity name/description")
    stage: OpportunityStage = Field(
        OpportunityStage.DISCOVERY, description="Current pipeline stage"
    )
    value: float | None = Field(None, description="Estimated deal value")
    currency: str = Field("USD", description="Currency code")
    close_date_estimate: date | None = Field(None, description="Estimated close date")
    confidence: int = Field(
        50, ge=0, le=100, description="Win probability percentage (0-100)"
    )
    competitors: list[str] = Field(default_factory=list, description="Competing vendors")
    lead_source: LeadSource | None = Field(None, description="How this deal was sourced")
    lead_source_detail: str | None = Field(None, description="Extra context for lead source")
    loss_reason: str | None = Field(None, description="Reason if closed-lost")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_memory_content(self) -> str:
        """Serialize opportunity to memory-friendly format."""
        return self.model_dump_json()

    def to_memory_metadata(self) -> dict[str, Any]:
        """Generate memory metadata tags."""
        return {
            "type": "opportunity",
            "id": self.id,
            "customer_id": self.customer_id,
            "stage": self.stage.value,
        }


class ActionItem(BaseModel):
    """An action item from a meeting or activity."""

    id: str = Field(..., description="Unique action item identifier")
    description: str = Field(..., description="What needs to be done")
    owner: str | None = Field(None, description="Who is responsible")
    due_date: date | None = Field(None, description="When it's due")
    is_completed: bool = Field(False, description="Whether it's done")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PromotedActionItem(BaseModel):
    """A promoted action item stored as a top-level CRM object with lineage."""

    id: str = Field(..., description="Unique action item identifier")
    customer_id: str = Field(..., description="Parent customer ID")
    activity_id: str = Field(..., description="Source activity ID")
    thread_id: str = Field(..., description="Source meeting thread ID")
    description: str = Field(..., description="What needs to be done")
    owner: str | None = Field(None, description="Who is responsible")
    due_date: date | None = Field(None, description="When it's due")
    is_completed: bool = Field(False, description="Whether it's done")
    is_dismissed: bool = Field(False, description="Soft delete flag")
    source_excerpt: str | None = Field(
        None, description="Transcript excerpt that generated this action item"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_memory_content(self) -> str:
        """Serialize to memory-friendly format."""
        return self.model_dump_json()

    def to_memory_metadata(self) -> dict[str, Any]:
        """Generate memory metadata tags."""
        return {
            "type": "promoted_action_item",
            "id": self.id,
            "customer_id": self.customer_id,
            "activity_id": self.activity_id,
        }


class Activity(BaseModel):
    """A logged activity with a customer (meeting, call, email, etc.)."""

    id: str = Field(..., description="Unique activity identifier")
    customer_id: str = Field(..., description="Parent customer ID")
    opportunity_id: str | None = Field(None, description="Related opportunity ID if any")
    thread_id: str = Field(..., description="Backboard thread ID for this activity")
    activity_type: ActivityType = Field(..., description="Type of activity")
    date: datetime = Field(..., description="When the activity occurred")
    summary: str = Field(..., description="Brief summary of the activity")
    participants: list[str] = Field(default_factory=list, description="People involved")
    action_items: list[ActionItem] = Field(
        default_factory=list, description="Action items from this activity"
    )
    teammate_user_ids: list[str] = Field(
        default_factory=list,
        description="IDs of teammate users who were in this meeting",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def to_memory_content(self) -> str:
        """Serialize activity to memory-friendly format."""
        return self.model_dump_json()

    def to_memory_metadata(self) -> dict[str, Any]:
        """Generate memory metadata tags."""
        return {
            "type": "activity",
            "id": self.id,
            "customer_id": self.customer_id,
            "activity_type": self.activity_type.value,
            "date": self.date.isoformat(),
            "thread_id": self.thread_id,
        }


# Request/Response models for API
class CustomerCreate(BaseModel):
    """Request model for creating a customer."""

    company_name: str
    domain: str | None = None
    industry: str | None = None
    size: CustomerSize | None = None
    lead_source: LeadSource | None = None
    lead_source_detail: str | None = None


class ContactCreate(BaseModel):
    """Request model for creating a contact."""

    customer_id: str
    name: str
    email: str | None = None
    phone: str | None = None
    role: str | None = None
    linkedin_url: str | None = None
    is_champion: bool = False
    is_decision_maker: bool = False
    preferred_contact_method: ContactMethod | None = None


class OpportunityCreate(BaseModel):
    """Request model for creating an opportunity."""

    customer_id: str
    name: str
    stage: OpportunityStage = OpportunityStage.DISCOVERY
    value: float | None = None
    close_date_estimate: date | None = None
    confidence: int = 50
    competitors: list[str] = Field(default_factory=list)
    lead_source: LeadSource | None = None
    lead_source_detail: str | None = None


class OpportunityUpdate(BaseModel):
    """Request model for updating an opportunity."""

    name: str | None = None
    stage: OpportunityStage | None = None
    value: float | None = None
    close_date_estimate: date | None = None
    confidence: int | None = None
    competitors: list[str] | None = None
    lead_source: LeadSource | None = None
    lead_source_detail: str | None = None
    loss_reason: str | None = None


class PromotedActionItemUpdate(BaseModel):
    """Request model for updating a promoted action item."""

    description: str | None = None
    owner: str | None = None
    due_date: date | None = None
    is_completed: bool | None = None


class ContactUpdate(BaseModel):
    """Request model for updating a contact."""

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    role: str | None = None
    linkedin_url: str | None = None
    is_champion: bool | None = None
    is_decision_maker: bool | None = None
    preferred_contact_method: ContactMethod | None = None
    notes: str | None = None


class CustomerUpdate(BaseModel):
    """Request model for updating a customer."""

    company_name: str | None = None
    domain: str | None = None
    industry: str | None = None
    size: CustomerSize | None = None
    lead_source: LeadSource | None = None
    lead_source_detail: str | None = None
    next_followup_date: date | None = None
    assigned_user_id: str | None = None