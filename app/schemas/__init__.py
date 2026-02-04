"""Pydantic schemas for CloserNotes."""

from app.schemas.crm import (
    Activity,
    ActionItem as CRMActionItem,
    Contact,
    ContactCreate,
    Customer,
    CustomerCreate,
    Opportunity,
    OpportunityCreate,
    OpportunityUpdate,
    PromotedActionItem,
    PromotedActionItemUpdate,
)
from app.schemas.enums import ActivityType, CustomerSize, ContactRole, OpportunityStage
from app.schemas.meeting import (
    ActionItem,
    EntityExtraction,
    FollowupEmail,
    IngestRequest,
    IngestResponse,
    MeetingNotes,
    NewsHeadline,
    StakeholderMention,
    TranscriptMetadata,
)

__all__ = [
    # CRM
    "Customer",
    "CustomerCreate",
    "Contact",
    "ContactCreate",
    "Opportunity",
    "OpportunityCreate",
    "OpportunityUpdate",
    "Activity",
    "CRMActionItem",
    "PromotedActionItem",
    "PromotedActionItemUpdate",
    # Enums
    "OpportunityStage",
    "ActivityType",
    "CustomerSize",
    "ContactRole",
    # Meeting
    "MeetingNotes",
    "ActionItem",
    "StakeholderMention",
    "TranscriptMetadata",
    "IngestRequest",
    "IngestResponse",
    "EntityExtraction",
    "FollowupEmail",
    "NewsHeadline",
]
