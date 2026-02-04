"""Newsboard integration service for follow-up email generation."""

import json
import re
from datetime import datetime
from typing import Any

from app.config import get_settings
from app.prompts.followup import (
    get_relevance_prompt,
    get_followup_email_prompt,
    get_customer_matching_prompt,
)
from app.schemas.meeting import FollowupEmail, NewsHeadline
from app.services.backboard import BackboardService
from app.services.customer import CustomerService


class NewsboardService:
    """Service for integrating with Newsboard and generating follow-up emails."""

    def __init__(self, backboard: BackboardService):
        """Initialize the Newsboard service.

        Args:
            backboard: BackboardService instance
        """
        self._backboard = backboard
        self._settings = get_settings()
        self._customer_service = CustomerService(backboard)

    async def get_recent_headlines(
        self,
        limit: int = 10,
    ) -> list[NewsHeadline]:
        """Fetch recent headlines from the Newsboard assistant.

        Args:
            limit: Maximum number of headlines to fetch

        Returns:
            List of NewsHeadline objects
        """
        newsboard_id = self._settings.effective_newsboard_id
        if not newsboard_id:
            return []

        try:
            # Create a thread to query Newsboard
            thread = await self._backboard.create_thread(newsboard_id)

            # Query for recent headlines
            response = await self._backboard.send_message(
                thread_id=thread.thread_id,
                content=f"List the {limit} most recent news headlines with their tags and summaries. Format as JSON array.",
                memory="Readonly",
            )

            # Parse headlines from response
            return self._parse_headlines(response.content)

        except Exception:
            return []

    def _parse_headlines(self, content: str) -> list[NewsHeadline]:
        """Parse headlines from Newsboard response.

        Args:
            content: Response content from Newsboard

        Returns:
            List of NewsHeadline objects
        """
        headlines = []
        try:
            # Find JSON array in response
            json_match = re.search(r"\[[\s\S]*\]", content)
            if json_match:
                data = json.loads(json_match.group())
                for item in data:
                    if isinstance(item, dict):
                        headlines.append(
                            NewsHeadline(
                                id=item.get("id", str(len(headlines))),
                                title=item.get("title", ""),
                                summary=item.get("summary"),
                                source=item.get("source"),
                                url=item.get("url"),
                                tags=item.get("tags", []),
                                published_at=None,  # Would need date parsing
                            )
                        )
        except (json.JSONDecodeError, AttributeError):
            pass
        return headlines

    async def check_relevance(
        self,
        headline: NewsHeadline,
        customer_assistant_id: str,
    ) -> dict[str, Any]:
        """Check if a headline is relevant to a customer.

        Args:
            headline: The news headline
            customer_assistant_id: The customer's assistant ID

        Returns:
            Relevance assessment with score and reason
        """
        # Get customer context
        customer = await self._customer_service.get_customer(customer_assistant_id)
        if not customer:
            return {"is_relevant": False, "relevance_score": 0}

        pain_points = await self._customer_service.get_pain_points(customer_assistant_id)
        opportunities = await self._customer_service.get_opportunities(customer_assistant_id)
        recent_topics = await self._customer_service.get_recent_topics(customer_assistant_id)

        # Build relevance check prompt
        prompt = get_relevance_prompt(
            headline_title=headline.title,
            headline_summary=headline.summary,
            headline_tags=headline.tags,
            company_name=customer.company_name,
            customer_industry=customer.industry,
            pain_points=pain_points,
            opportunities=[o.name for o in opportunities],
            interests=recent_topics,
        )

        # Create a thread for relevance check
        thread = await self._backboard.create_thread(customer_assistant_id)

        response = await self._backboard.send_message(
            thread_id=thread.thread_id,
            content=prompt,
            memory="Readonly",
        )

        # Parse relevance response
        try:
            json_match = re.search(r"\{[\s\S]*\}", response.content)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, AttributeError):
            pass

        return {"is_relevant": False, "relevance_score": 0}

    async def generate_followup_email(
        self,
        headline: NewsHeadline,
        customer_assistant_id: str,
        relevance_reason: str,
    ) -> FollowupEmail | None:
        """Generate a personalized follow-up email for a customer.

        Args:
            headline: The triggering news headline
            customer_assistant_id: The customer's assistant ID
            relevance_reason: Why this news is relevant

        Returns:
            Generated FollowupEmail or None if generation fails
        """
        # Get customer context
        customer = await self._customer_service.get_customer(customer_assistant_id)
        if not customer:
            return None

        contacts = await self._customer_service.get_contacts(customer_assistant_id)
        pain_points = await self._customer_service.get_pain_points(customer_assistant_id)
        recent_topics = await self._customer_service.get_recent_topics(customer_assistant_id)

        # Find primary contact (champion or decision maker preferred)
        primary_contact = None
        for contact in contacts:
            if contact.is_champion or contact.is_decision_maker:
                primary_contact = contact
                break
        if not primary_contact and contacts:
            primary_contact = contacts[0]

        # Build email generation prompt
        prompt = get_followup_email_prompt(
            headline_title=headline.title,
            headline_summary=headline.summary,
            headline_source=headline.source,
            company_name=customer.company_name,
            contact_name=primary_contact.name if primary_contact else None,
            contact_role=primary_contact.role if primary_contact else None,
            recent_topics=recent_topics,
            pain_points=pain_points,
            relevance_reason=relevance_reason,
        )

        # Create a thread for email generation
        thread = await self._backboard.create_thread(customer_assistant_id)

        response = await self._backboard.send_message(
            thread_id=thread.thread_id,
            content=prompt,
            memory="Readonly",
        )

        # Parse email response
        try:
            json_match = re.search(r"\{[\s\S]*\}", response.content)
            if json_match:
                data = json.loads(json_match.group())
                return FollowupEmail(
                    customer_id=customer.id,
                    customer_name=customer.company_name,
                    contact_name=primary_contact.name if primary_contact else None,
                    contact_email=primary_contact.email if primary_contact else None,
                    subject=data.get("subject", "Follow-up"),
                    body=data.get("body", ""),
                    headline_source=headline.title,
                    relevance_reason=relevance_reason,
                    generated_at=datetime.utcnow(),
                )
        except (json.JSONDecodeError, AttributeError):
            pass

        return None

    async def find_impacted_customers(
        self,
        headline: NewsHeadline,
        customer_assistant_ids: list[str],
        relevance_threshold: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Find customers impacted by a news headline.

        Args:
            headline: The news headline
            customer_assistant_ids: List of customer assistant IDs to check
            relevance_threshold: Minimum relevance score

        Returns:
            List of impacted customers with relevance info
        """
        impacted = []

        for assistant_id in customer_assistant_ids:
            relevance = await self.check_relevance(headline, assistant_id)

            if relevance.get("is_relevant") and relevance.get("relevance_score", 0) >= relevance_threshold:
                customer = await self._customer_service.get_customer(assistant_id)
                if customer:
                    impacted.append({
                        "customer_id": customer.id,
                        "customer_name": customer.company_name,
                        "assistant_id": assistant_id,
                        "relevance_score": relevance.get("relevance_score"),
                        "relevance_reason": relevance.get("relevance_reason"),
                        "suggested_angle": relevance.get("suggested_angle"),
                        "urgency": relevance.get("urgency", "medium"),
                    })

        # Sort by relevance score descending
        impacted.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

        return impacted

    async def generate_followups_for_headlines(
        self,
        customer_assistant_ids: list[str],
        headline_limit: int = 5,
        relevance_threshold: float = 0.6,
    ) -> list[FollowupEmail]:
        """Generate follow-up emails for recent headlines.

        This is the main entry point for the follow-up workflow.

        Args:
            customer_assistant_ids: List of customer assistant IDs
            headline_limit: Maximum headlines to process
            relevance_threshold: Minimum relevance score

        Returns:
            List of generated FollowupEmail objects
        """
        followups = []

        # Get recent headlines
        headlines = await self.get_recent_headlines(limit=headline_limit)

        for headline in headlines:
            # Find impacted customers
            impacted = await self.find_impacted_customers(
                headline=headline,
                customer_assistant_ids=customer_assistant_ids,
                relevance_threshold=relevance_threshold,
            )

            # Generate emails for impacted customers
            for customer_info in impacted:
                email = await self.generate_followup_email(
                    headline=headline,
                    customer_assistant_id=customer_info["assistant_id"],
                    relevance_reason=customer_info.get("relevance_reason", ""),
                )
                if email:
                    followups.append(email)

        return followups


def get_newsboard_service(backboard: BackboardService) -> NewsboardService:
    """Get a NewsboardService instance.

    Args:
        backboard: BackboardService instance to use

    Returns:
        NewsboardService instance
    """
    return NewsboardService(backboard)
