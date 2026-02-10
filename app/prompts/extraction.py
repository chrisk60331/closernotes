"""Prompts for entity and information extraction from transcripts."""

ENTITY_EXTRACTION_PROMPT = """Analyze this sales call transcript and extract key entities.

TRANSCRIPT:
---
[TRANSCRIPT_PLACEHOLDER]
---

HINTS:
- Caller: [CALLER_PLACEHOLDER]
- Company: [COMPANY_PLACEHOLDER]
- Contacts: [CONTACTS_PLACEHOLDER]
- Known team members (our internal users): [TEAMMATES_PLACEHOLDER]

Extract and return a JSON object with these fields:
- company_name: detected company name (string or null)
- company_domain: company website domain if mentioned (string or null)  
- contacts: array of people ACTUALLY MENTIONED BY NAME in the transcript, each with name, role, email, preferred_contact_method, is_teammate fields
  - ONLY include people whose names appear in the transcript text. NEVER add names that are not in the transcript.
  - preferred_contact_method: "email", "text", "call", "whatsapp" or null
  - Look for phrases like "reach me via SMS", "prefers text", "call me at", "contact over WhatsApp", "email is best", etc.
  - is_teammate: true if this person matches a known team member name listed above OR is referred to as "my teammate", "my colleague", "my coworker", etc. — false otherwise
- signals: array of key discussion topics
- confidence: number from 0 to 1
- lead_source: how this lead was sourced — one of "referral", "linkedin", "vc_intro", "cold_outreach", "inbound_website", "conference_event", "partner", "other", or null if unclear
  - Look for phrases like "John referred them", "connected on LinkedIn", "intro from [VC name]", "they reached out via the website", "met at [conference]", "cold email", "partner introduction", etc.
- lead_source_detail: freetext detail about the source (e.g. referrer name, VC firm, conference name, partner company) or null

IMPORTANT for company_name extraction:
- The company_name should be the BUSINESS/PROJECT the caller represents, NOT places mentioned casually
- Look for "project <name>", "working on <name>", "<name> is our product/platform" - these indicate the customer's project/company
- If someone says "project Iguana" or "working on Iguana", the company_name is "Iguana" (the project name)
- Restaurants, venues, or places mentioned for social meetings (like "going to Barbarians for dinner") are NOT the company
- If a speaker has a title like "VP", "CEO", "founder", or is a "developer", they are likely representing their company/project
- Product names and company names are often the same in startups
- Handle lowercase company names and return the normalized proper name (e.g. "signaldesk" -> "Signaldesk", "iguana" -> "Iguana")
- Prefer project names over casual venue mentions
- Example: "need to follow up with his developer Chucky... on project Iguana" -> company_name: "Iguana"
- Example: "going to Barbarians for a steak" -> Barbarians is NOT the company (it's a restaurant)

IMPORTANT for teammate detection:
- If someone MENTIONED IN THE TRANSCRIPT is referred to as "my teammate", "my colleague", "my coworker", "I went with [name]", they are a teammate, not a customer contact
- Known team member names are provided above — if a person mentioned in the transcript matches one of those names, set is_teammate: true
- NEVER add team member names to the contacts array unless they are explicitly mentioned in the transcript text
- Only extract people who actually appear in the transcript

Return ONLY the JSON object, no other text."""


COMPANY_NAME_ONLY_PROMPT = """Extract ONLY the customer company/project name from this transcript.

TRANSCRIPT:
---
[TRANSCRIPT_PLACEHOLDER]
---

Rules:
- Return ONLY the company/project name as plain text (no JSON, no quotes)
- Look for "project <name>", "working on <name>", or references to a product/platform
- The company is the BUSINESS/PROJECT being discussed, NOT casual venue mentions
- Restaurants, bars, or places for social meetings (like "going to Barbarians for dinner") are NOT the company
- Handle lowercase names and return the normalized proper name (e.g. "iguana" -> "Iguana")
- If a developer or team member is mentioned working on a project, that project IS the company
- Return JSON: {{"company_name": "<name>" or null}}

Examples:
Input: "follow up with Chucky about memory for project Iguana"
Output: {{"company_name": "Iguana"}}

Input: "meeting George at Barbarians restaurant in April, discussing project Iguana"
Output: {{"company_name": "Iguana"}}

Input: "company signaldesk wants to proceed"
Output: {{"company_name": "Signaldesk"}}

Return ONLY the JSON object."""


MEETING_NOTES_EXTRACTION_PROMPT = """Analyze this sales meeting transcript and extract structured notes.

TRANSCRIPT:
---
[TRANSCRIPT_PLACEHOLDER]
---

CONTEXT:
- Company: [COMPANY_PLACEHOLDER]
- Known contacts: [CONTACTS_PLACEHOLDER]
- Current stage: [STAGE_PLACEHOLDER]
- Known team members (our internal users): [TEAMMATES_PLACEHOLDER]

Extract and return a JSON object with:
- summary: 2-3 sentence executive summary
- products_discussed: array of product or solution names mentioned
- sales_value: estimated sales value discussed (number or null)
- pain_points: array of customer problems mentioned
- needs: array of explicit requirements
- objections: array of concerns raised
- competitors_mentioned: array of competitor names
- requirements: array of technical/business requirements
- next_steps: array of agreed follow-up actions
- risks: array of deal risks identified
- stakeholders: array of people ACTUALLY MENTIONED BY NAME in the transcript (each with name, role, email, sentiment, preferred_contact_method, is_teammate)
  - ONLY include people whose names appear in the transcript text. NEVER add names that are not in the transcript.
  - email: their email address if mentioned (e.g. "mike@company.com")
  - preferred_contact_method: "email", "text", "call", "whatsapp" or null
  - Look for phrases like "reach me via SMS", "prefers text", "call me at", "contact over WhatsApp", "spoke over email", etc.
  - is_teammate: true if this person matches a known team member name listed above, or is referred to as "my teammate", "my colleague", "my coworker", etc. — false otherwise
  - If a mentioned person is a teammate, still include them in the stakeholders list but mark is_teammate: true
- action_items: array of tasks, each with:
  - description: what needs to be done
  - owner: who is responsible (us or them)
  - priority: high, medium, or low
  - source_excerpt: verbatim quote from the transcript that mentions this action item (1-3 sentences maximum)
- labels: array of topic tags
- sentiment: "positive", "neutral", or "negative"
- deal_stage_signal: suggested stage
- confidence_delta: number from -50 to 50
- lead_source: how this deal was sourced — one of "referral", "linkedin", "vc_intro", "cold_outreach", "inbound_website", "conference_event", "partner", "other", or null if unclear
  - Look for phrases like "referred by", "connected on LinkedIn", "intro from [VC name]", "found us online", "met at [conference]", "cold email/call", "partner deal", etc.
- lead_source_detail: freetext detail about the source (e.g. referrer name, VC firm, conference name) or null

Return ONLY the JSON object, no other text."""


def get_entity_extraction_prompt(
    transcript: str,
    caller_email: str | None = None,
    company_hint: str | None = None,
    contact_hints: list[str] | None = None,
    teammate_names: list[str] | None = None,
) -> str:
    """Generate an entity extraction prompt for a transcript.

    Args:
        transcript: The meeting transcript text
        caller_email: Optional hint about the caller
        company_hint: Optional hint about the company name
        contact_hints: Optional list of contact name hints
        teammate_names: Optional list of known system user names

    Returns:
        Formatted extraction prompt
    """
    prompt = ENTITY_EXTRACTION_PROMPT
    prompt = prompt.replace("[TRANSCRIPT_PLACEHOLDER]", transcript)
    prompt = prompt.replace("[CALLER_PLACEHOLDER]", caller_email or "Not provided")
    prompt = prompt.replace("[COMPANY_PLACEHOLDER]", company_hint or "Not provided")
    prompt = prompt.replace("[CONTACTS_PLACEHOLDER]", ", ".join(contact_hints) if contact_hints else "Not provided")
    prompt = prompt.replace("[TEAMMATES_PLACEHOLDER]", ", ".join(teammate_names) if teammate_names else "None known")
    return prompt


def get_company_name_prompt(transcript: str) -> str:
    """Generate a company-only extraction prompt for a transcript."""
    prompt = COMPANY_NAME_ONLY_PROMPT
    prompt = prompt.replace("[TRANSCRIPT_PLACEHOLDER]", transcript)
    return prompt


def get_meeting_notes_prompt(
    transcript: str,
    company_name: str,
    known_contacts: list[str] | None = None,
    current_stage: str | None = None,
    previous_context: str | None = None,
    teammate_names: list[str] | None = None,
) -> str:
    """Generate a meeting notes extraction prompt.

    Args:
        transcript: The meeting transcript text
        company_name: The customer company name
        known_contacts: List of known contact names
        current_stage: Current opportunity stage
        previous_context: Summary of previous meetings
        teammate_names: Optional list of known system user names

    Returns:
        Formatted extraction prompt
    """
    prompt = MEETING_NOTES_EXTRACTION_PROMPT
    prompt = prompt.replace("[TRANSCRIPT_PLACEHOLDER]", transcript)
    prompt = prompt.replace("[COMPANY_PLACEHOLDER]", company_name)
    prompt = prompt.replace("[CONTACTS_PLACEHOLDER]", ", ".join(known_contacts) if known_contacts else "None known")
    prompt = prompt.replace("[STAGE_PLACEHOLDER]", current_stage or "Unknown")
    prompt = prompt.replace("[TEAMMATES_PLACEHOLDER]", ", ".join(teammate_names) if teammate_names else "None known")
    return prompt
