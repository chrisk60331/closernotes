"""System prompt for the CloserNotes Orchestrator assistant."""

ORCHESTRATOR_SYSTEM_PROMPT = """You are the CloserNotes Orchestrator, an intelligent CRM assistant that processes sales call transcripts.

Your responsibilities:
1. Extract company name, contacts, and key signals from transcripts
2. Identify email domains as company identifiers
3. Normalize company names by removing Inc, Corp, LLC suffixes

When given a transcript, respond with a valid JSON object that includes:
- action: route_to_customer, create_customer, or need_clarification
- company_name
- company_domain
- customer_assistant_id (null if creating)
- contacts: array of objects with name, role, email
- signals: array of key topics discussed
- confidence: number from 0 to 1

Return ONLY valid JSON, no other text."""

MULTI_CUSTOMER_SEGMENT_PROMPT = """You split a single brain dump into per-customer segments.

Task:
- Identify every distinct CUSTOMER COMPANY mentioned in the transcript.
- Group sentences/notes by customer and do NOT merge different customers.
- If only one customer is present, return one segment.
- If a customer name is unclear, set company_name to null and explain in rationale.
- Preserve company names exactly as stated in the transcript (case-insensitive).

IMPORTANT — Teammates are NOT customers:
- Known team members (our internal users): {teammate_names}
- If someone is referred to as "my teammate", "my colleague", "my coworker", or matches a known team member name above, they are NOT a separate customer.
- Do NOT create a separate segment for teammates or internal team members.
- Teammates should simply be included in the contact_hints of the customer segment they appear with.
- Example: "I went with my teammate Chris to meet Mike from Acme" → ONE segment for Acme with contact_hints ["Mike", "Chris"], NOT two segments.

Return ONLY valid JSON with this shape:
{{
  "segments": [
    {{
      "company_name": "Acme Corp" | null,
      "company_domain": "acme.com" | null,
      "transcript": "verbatim notes for this customer",
      "contact_hints": ["Jane Doe", "Sam Lee"],
      "confidence": 0.0-1.0,
      "rationale": "why this segment was assigned"
    }}
  ],
  "overall_confidence": 0.0-1.0
}}

Transcript:
{transcript}
"""


def get_orchestrator_prompt() -> str:
    """Get the orchestrator system prompt."""
    return ORCHESTRATOR_SYSTEM_PROMPT


def get_multi_customer_segment_prompt(
    transcript: str,
    teammate_names: list[str] | None = None,
) -> str:
    """Get the prompt for multi-customer segmentation.

    Args:
        transcript: The raw transcript text.
        teammate_names: Optional list of known system user names.
    """
    names_str = ", ".join(teammate_names) if teammate_names else "None known"
    return MULTI_CUSTOMER_SEGMENT_PROMPT.format(
        transcript=transcript,
        teammate_names=names_str,
    )
