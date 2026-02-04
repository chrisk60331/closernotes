"""Follow-up email generation API endpoints."""

import asyncio
from flask import Blueprint, request, jsonify, current_app

from app.services.backboard import BackboardService
from app.services.orchestrator import OrchestratorService
from app.services.newsboard import NewsboardService

followup_bp = Blueprint("followup", __name__)


def run_async(coro):
    """Run an async coroutine in a sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@followup_bp.route("/followup/generate", methods=["POST"])
def generate_followups():
    """Generate follow-up emails based on recent Newsboard headlines.

    Request body (optional):
        {
            "headline_limit": 5,
            "relevance_threshold": 0.6,
            "customer_ids": ["assistant-id-1", "assistant-id-2"]  // optional filter
        }

    Returns:
        JSON array of generated follow-up emails
    """
    try:
        json_data = request.get_json() or {}

        headline_limit = json_data.get("headline_limit", 5)
        relevance_threshold = json_data.get("relevance_threshold", 0.6)
        customer_filter = json_data.get("customer_ids")

        async def _generate():
            backboard = BackboardService()
            orchestrator = OrchestratorService(backboard)
            newsboard_svc = NewsboardService(backboard)

            await orchestrator.ensure_orchestrator_exists()

            # Get customer list
            if customer_filter:
                customer_assistant_ids = customer_filter
            else:
                customers = await orchestrator.get_all_customers()
                customer_assistant_ids = [c["assistant_id"] for c in customers]

            if not customer_assistant_ids:
                return []

            # Generate follow-ups
            followups = await newsboard_svc.generate_followups_for_headlines(
                customer_assistant_ids=customer_assistant_ids,
                headline_limit=headline_limit,
                relevance_threshold=relevance_threshold,
            )

            return [f.model_dump(mode="json") for f in followups]

        followups = run_async(_generate())
        return jsonify({
            "followups": followups,
            "count": len(followups),
        }), 200

    except Exception as e:
        current_app.logger.exception("Error generating follow-ups")
        return jsonify({"error": str(e)}), 500


@followup_bp.route("/followup/headlines", methods=["GET"])
def get_recent_headlines():
    """Get recent headlines from Newsboard.

    Query params:
        limit: Maximum number to return (default 10)

    Returns:
        JSON array of headlines
    """
    try:
        limit = request.args.get("limit", 10, type=int)

        async def _get():
            backboard = BackboardService()
            newsboard_svc = NewsboardService(backboard)
            headlines = await newsboard_svc.get_recent_headlines(limit=limit)
            return [h.model_dump(mode="json") for h in headlines]

        headlines = run_async(_get())
        return jsonify({"headlines": headlines}), 200

    except Exception as e:
        current_app.logger.exception("Error getting headlines")
        return jsonify({"error": str(e)}), 500


@followup_bp.route("/followup/check-relevance", methods=["POST"])
def check_headline_relevance():
    """Check if a headline is relevant to a customer.

    Request body:
        {
            "headline": {
                "id": "headline-1",
                "title": "AI Startup Raises $100M",
                "summary": "...",
                "tags": ["AI", "funding"]
            },
            "customer_assistant_id": "assistant-id"
        }

    Returns:
        JSON with relevance assessment
    """
    try:
        json_data = request.get_json()
        if not json_data:
            return jsonify({"error": "Request body is required"}), 400

        headline_data = json_data.get("headline")
        assistant_id = json_data.get("customer_assistant_id")

        if not headline_data or not assistant_id:
            return jsonify({"error": "headline and customer_assistant_id are required"}), 400

        async def _check():
            from app.schemas.meeting import NewsHeadline

            backboard = BackboardService()
            newsboard_svc = NewsboardService(backboard)

            headline = NewsHeadline.model_validate(headline_data)
            return await newsboard_svc.check_relevance(headline, assistant_id)

        relevance = run_async(_check())
        return jsonify({"relevance": relevance}), 200

    except Exception as e:
        current_app.logger.exception("Error checking relevance")
        return jsonify({"error": str(e)}), 500


@followup_bp.route("/followup/generate-single", methods=["POST"])
def generate_single_followup():
    """Generate a follow-up email for a specific headline and customer.

    Request body:
        {
            "headline": {
                "id": "headline-1",
                "title": "AI Startup Raises $100M",
                "summary": "...",
                "source": "TechCrunch",
                "tags": ["AI", "funding"]
            },
            "customer_assistant_id": "assistant-id",
            "relevance_reason": "They're also in the AI space"
        }

    Returns:
        JSON with generated email
    """
    try:
        json_data = request.get_json()
        if not json_data:
            return jsonify({"error": "Request body is required"}), 400

        headline_data = json_data.get("headline")
        assistant_id = json_data.get("customer_assistant_id")
        relevance_reason = json_data.get("relevance_reason", "")

        if not headline_data or not assistant_id:
            return jsonify({"error": "headline and customer_assistant_id are required"}), 400

        async def _generate():
            from app.schemas.meeting import NewsHeadline

            backboard = BackboardService()
            newsboard_svc = NewsboardService(backboard)

            headline = NewsHeadline.model_validate(headline_data)
            email = await newsboard_svc.generate_followup_email(
                headline=headline,
                customer_assistant_id=assistant_id,
                relevance_reason=relevance_reason,
            )
            return email.model_dump(mode="json") if email else None

        email = run_async(_generate())
        if not email:
            return jsonify({"error": "Failed to generate email"}), 500

        return jsonify({"email": email}), 200

    except Exception as e:
        current_app.logger.exception("Error generating email")
        return jsonify({"error": str(e)}), 500
