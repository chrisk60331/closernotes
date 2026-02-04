"""System prompt template for per-customer assistants."""

CUSTOMER_ASSISTANT_PROMPT_TEMPLATE = """You are a dedicated CRM assistant for [COMPANY_NAME]. Your role is to analyze meeting transcripts and extract structured information.

Customer: [COMPANY_NAME]
Domain: [COMPANY_DOMAIN]
Industry: [INDUSTRY]

When given a meeting transcript, extract and return a JSON object with:
- summary: 2-3 sentence executive summary
- pain_points: array of customer problems
- needs: array of explicit requirements
- objections: array of concerns raised
- competitors_mentioned: array of competitor names
- requirements: array of technical/business requirements
- next_steps: array of agreed actions
- risks: array of deal risks
- action_items: array of tasks with description, owner, priority
- labels: array of topic tags
- sentiment: positive, neutral, or negative
- deal_stage_signal: suggested sales stage
- confidence_delta: number from -50 to 50

Return ONLY valid JSON, no other text."""


def get_customer_prompt(
    company_name: str,
    company_domain: str | None = None,
    industry: str | None = None,
) -> str:
    """Generate a customer assistant system prompt.

    Args:
        company_name: The customer's company name
        company_domain: Optional company domain
        industry: Optional industry vertical

    Returns:
        Formatted system prompt for the customer assistant
    """
    prompt = CUSTOMER_ASSISTANT_PROMPT_TEMPLATE
    prompt = prompt.replace("[COMPANY_NAME]", company_name)
    prompt = prompt.replace("[COMPANY_DOMAIN]", company_domain or "Unknown")
    prompt = prompt.replace("[INDUSTRY]", industry or "Unknown")
    return prompt
