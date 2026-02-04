"""Tool definitions for Backboard assistant function calling."""

from typing import Any

# Tool definitions following OpenAI function calling format
# These are used when creating assistants with tool capabilities

FIND_OR_CREATE_CUSTOMER_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "find_or_create_customer",
        "description": (
            "Find an existing customer by company name or domain, or create a new customer "
            "assistant if none exists. Returns the customer assistant ID for further operations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "company_name": {
                    "type": "string",
                    "description": "The company name to search for or create",
                },
                "company_domain": {
                    "type": "string",
                    "description": "The company's domain (e.g., acme.com) for matching",
                },
                "industry": {
                    "type": "string",
                    "description": "The company's industry vertical if known",
                },
                "size": {
                    "type": "string",
                    "enum": ["startup", "smb", "mid_market", "enterprise"],
                    "description": "Company size category if known",
                },
            },
            "required": ["company_name"],
        },
    },
}

CREATE_MEETING_THREAD_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_meeting_thread",
        "description": (
            "Create a new thread for a meeting/call under a customer assistant. "
            "Returns the thread ID for storing the meeting transcript and notes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_assistant_id": {
                    "type": "string",
                    "description": "The customer assistant ID to create the thread under",
                },
                "meeting_type": {
                    "type": "string",
                    "enum": ["meeting", "call", "demo", "discovery", "negotiation", "other"],
                    "description": "Type of meeting/call",
                },
                "meeting_date": {
                    "type": "string",
                    "description": "ISO format date/time of the meeting",
                },
                "participants": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names of people who participated in the meeting",
                },
            },
            "required": ["customer_assistant_id"],
        },
    },
}

EXTRACT_ENTITIES_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "extract_entities",
        "description": (
            "Extract entities (company, contacts, signals) from a transcript. "
            "Used to determine routing before creating customer assistant."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "transcript": {
                    "type": "string",
                    "description": "The meeting transcript text to analyze",
                },
                "caller_hint": {
                    "type": "string",
                    "description": "Optional hint about who made the call (e.g., email)",
                },
                "company_hint": {
                    "type": "string",
                    "description": "Optional hint about the company name",
                },
            },
            "required": ["transcript"],
        },
    },
}

EXTRACT_MEETING_NOTES_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "extract_meeting_notes",
        "description": (
            "Extract structured meeting notes from a transcript. Includes summary, "
            "pain points, needs, objections, action items, and more."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "transcript": {
                    "type": "string",
                    "description": "The meeting transcript text to analyze",
                },
                "company_context": {
                    "type": "string",
                    "description": "Context about the customer company",
                },
                "previous_meetings_summary": {
                    "type": "string",
                    "description": "Summary of previous meetings for context",
                },
            },
            "required": ["transcript"],
        },
    },
}

UPDATE_CRM_OBJECT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "update_crm_object",
        "description": (
            "Create or update a CRM object (contact, opportunity, activity) in memory. "
            "The object is stored in the customer assistant's memory."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "object_type": {
                    "type": "string",
                    "enum": ["contact", "opportunity", "activity"],
                    "description": "Type of CRM object to create/update",
                },
                "customer_id": {
                    "type": "string",
                    "description": "The customer ID this object belongs to",
                },
                "object_data": {
                    "type": "object",
                    "description": "The object data as a JSON object",
                },
                "object_id": {
                    "type": "string",
                    "description": "Existing object ID for updates (omit for create)",
                },
            },
            "required": ["object_type", "customer_id", "object_data"],
        },
    },
}

SEARCH_CUSTOMERS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_customers",
        "description": (
            "Search for customers matching given criteria. Used for follow-up "
            "generation and customer matching."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (company name, industry, or keywords)",
                },
                "industry": {
                    "type": "string",
                    "description": "Filter by industry",
                },
                "has_active_opportunity": {
                    "type": "boolean",
                    "description": "Only return customers with active opportunities",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return",
                },
            },
            "required": [],
        },
    },
}

GENERATE_FOLLOWUP_EMAIL_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "generate_followup_email",
        "description": (
            "Generate a personalized follow-up email for a customer based on "
            "a news headline or other trigger."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "The customer to generate follow-up for",
                },
                "headline_title": {
                    "type": "string",
                    "description": "The news headline triggering the follow-up",
                },
                "headline_summary": {
                    "type": "string",
                    "description": "Summary of the news article",
                },
                "relevance_reason": {
                    "type": "string",
                    "description": "Why this news is relevant to this customer",
                },
            },
            "required": ["customer_id", "headline_title", "relevance_reason"],
        },
    },
}


def get_orchestrator_tools() -> list[dict[str, Any]]:
    """Get the list of tools for the orchestrator assistant."""
    return [
        FIND_OR_CREATE_CUSTOMER_TOOL,
        CREATE_MEETING_THREAD_TOOL,
        EXTRACT_ENTITIES_TOOL,
        SEARCH_CUSTOMERS_TOOL,
        GENERATE_FOLLOWUP_EMAIL_TOOL,
    ]


def get_customer_assistant_tools() -> list[dict[str, Any]]:
    """Get the list of tools for customer assistants."""
    return [
        EXTRACT_MEETING_NOTES_TOOL,
        UPDATE_CRM_OBJECT_TOOL,
    ]


# All tools as a dict for lookup
ALL_TOOLS: dict[str, dict[str, Any]] = {
    "find_or_create_customer": FIND_OR_CREATE_CUSTOMER_TOOL,
    "create_meeting_thread": CREATE_MEETING_THREAD_TOOL,
    "extract_entities": EXTRACT_ENTITIES_TOOL,
    "extract_meeting_notes": EXTRACT_MEETING_NOTES_TOOL,
    "update_crm_object": UPDATE_CRM_OBJECT_TOOL,
    "search_customers": SEARCH_CUSTOMERS_TOOL,
    "generate_followup_email": GENERATE_FOLLOWUP_EMAIL_TOOL,
}
