"""Prompts for follow-up email generation from news headlines."""

CUSTOMER_RELEVANCE_PROMPT = """Analyze whether this news headline is relevant to the customer and worth a follow-up.

## News Headline
Title: {headline_title}
Summary: {headline_summary}
Tags: {headline_tags}

## Customer Context
Company: {company_name}
Industry: {customer_industry}
Recent Pain Points: {pain_points}
Current Opportunities: {opportunities}
Key Interests: {interests}

## Instructions

Determine if this news is relevant enough to warrant a personalized follow-up email.

Consider:
1. Industry alignment - is this news about their industry?
2. Pain point relevance - does this relate to problems they've mentioned?
3. Opportunity context - could this affect their buying decision?
4. Timeliness - is this actionable now?

## Response Format

Respond with ONLY valid JSON:
```json
{{
  "is_relevant": true/false,
  "relevance_score": 0.0 to 1.0,
  "relevance_reason": "Brief explanation of why this is relevant",
  "suggested_angle": "How to frame this in an email",
  "urgency": "high/medium/low"
}}
```

Be selective - only return is_relevant: true for genuinely valuable follow-ups.
"""


FOLLOWUP_EMAIL_PROMPT = """Generate a personalized follow-up email based on this news headline.

## News Context
Title: {headline_title}
Summary: {headline_summary}
Source: {headline_source}

## Customer Context
Company: {company_name}
Contact: {contact_name}
Their Role: {contact_role}
Recent Discussion Topics: {recent_topics}
Their Pain Points: {pain_points}
Relevance Reason: {relevance_reason}

## Instructions

Write a brief, personalized follow-up email that:
1. References the news naturally
2. Connects it to their specific situation or pain points
3. Provides value or insight
4. Has a soft call-to-action (not salesy)
5. Sounds human and conversational

Keep it under 150 words. No corporate jargon.

## Response Format

Respond with ONLY valid JSON:
```json
{{
  "subject": "Email subject line",
  "body": "Full email body with appropriate greeting and signature placeholder",
  "tone": "helpful/urgent/casual/professional"
}}
```
"""


CUSTOMER_MATCHING_PROMPT = """Given these news headlines, identify which customers from our list might find each relevant.

## Headlines
{headlines_json}

## Customer List
{customers_json}

## Instructions

For each headline, identify customers who might benefit from a follow-up about it.

Consider:
- Industry alignment
- Known pain points and interests
- Current deal stage (active deals = higher priority)
- Recency of last contact

## Response Format

Respond with ONLY valid JSON:
```json
{{
  "matches": [
    {{
      "headline_id": "headline ID",
      "customer_matches": [
        {{
          "customer_id": "customer ID",
          "relevance_score": 0.0 to 1.0,
          "reason": "Brief reason for match"
        }}
      ]
    }}
  ]
}}
```

Only include matches with relevance_score > 0.5.
"""


def get_relevance_prompt(
    headline_title: str,
    headline_summary: str | None,
    headline_tags: list[str],
    company_name: str,
    customer_industry: str | None,
    pain_points: list[str],
    opportunities: list[str],
    interests: list[str],
) -> str:
    """Generate a relevance check prompt for a headline and customer."""
    return CUSTOMER_RELEVANCE_PROMPT.format(
        headline_title=headline_title,
        headline_summary=headline_summary or "No summary available",
        headline_tags=", ".join(headline_tags) if headline_tags else "None",
        company_name=company_name,
        customer_industry=customer_industry or "Unknown",
        pain_points=", ".join(pain_points) if pain_points else "None recorded",
        opportunities=", ".join(opportunities) if opportunities else "None active",
        interests=", ".join(interests) if interests else "None recorded",
    )


def get_followup_email_prompt(
    headline_title: str,
    headline_summary: str | None,
    headline_source: str | None,
    company_name: str,
    contact_name: str | None,
    contact_role: str | None,
    recent_topics: list[str],
    pain_points: list[str],
    relevance_reason: str,
) -> str:
    """Generate a follow-up email prompt."""
    return FOLLOWUP_EMAIL_PROMPT.format(
        headline_title=headline_title,
        headline_summary=headline_summary or "No summary available",
        headline_source=headline_source or "Unknown source",
        company_name=company_name,
        contact_name=contact_name or "the team",
        contact_role=contact_role or "Unknown",
        recent_topics=", ".join(recent_topics) if recent_topics else "General discussion",
        pain_points=", ".join(pain_points) if pain_points else "Not specified",
        relevance_reason=relevance_reason,
    )


def get_customer_matching_prompt(
    headlines_json: str,
    customers_json: str,
) -> str:
    """Generate a prompt to match headlines to relevant customers."""
    return CUSTOMER_MATCHING_PROMPT.format(
        headlines_json=headlines_json,
        customers_json=customers_json,
    )
