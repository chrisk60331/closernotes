"""Enum definitions for CloserNotes schemas."""

from enum import Enum


class OpportunityStage(str, Enum):
    """Sales opportunity pipeline stages."""

    DISCOVERY = "discovery"
    QUALIFICATION = "qualification"
    PROPOSAL = "proposal"
    NEGOTIATION = "negotiation"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"
    DELIVERED = "delivered"
    BLOCKED = "blocked"


class ActivityType(str, Enum):
    """Types of sales activities."""

    MEETING = "meeting"
    CALL = "call"
    EMAIL = "email"
    TASK = "task"
    NOTE = "note"


class CustomerSize(str, Enum):
    """Customer company size categories."""

    STARTUP = "startup"
    SMB = "smb"
    MID_MARKET = "mid_market"
    ENTERPRISE = "enterprise"


class ContactRole(str, Enum):
    """Standard contact roles in sales process."""

    CHAMPION = "champion"
    DECISION_MAKER = "decision_maker"
    INFLUENCER = "influencer"
    TECHNICAL_BUYER = "technical_buyer"
    ECONOMIC_BUYER = "economic_buyer"
    END_USER = "end_user"
    BLOCKER = "blocker"
    OTHER = "other"


class ContactMethod(str, Enum):
    """Preferred communication methods."""

    EMAIL = "email"
    TEXT = "text"
    CALL = "call"
    WHATSAPP = "whatsapp"


class LeadSource(str, Enum):
    """How a customer or opportunity was sourced."""

    REFERRAL = "referral"
    LINKEDIN = "linkedin"
    VC_INTRO = "vc_intro"
    COLD_OUTREACH = "cold_outreach"
    INBOUND_WEBSITE = "inbound_website"
    CONFERENCE_EVENT = "conference_event"
    PARTNER = "partner"
    OTHER = "other"
