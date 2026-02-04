"""Meeting API endpoints."""

import asyncio
from flask import Blueprint, request, jsonify, current_app

from app.services.backboard import BackboardService
from app.services.meeting import MeetingService

meetings_bp = Blueprint("meetings", __name__)


def run_async(coro):
    """Run an async coroutine in a sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@meetings_bp.route("/meetings/<thread_id>", methods=["GET"])
def get_meeting(thread_id: str):
    """Get a meeting by thread ID.

    Args:
        thread_id: The meeting thread ID

    Returns:
        JSON with meeting details and messages
    """
    try:
        async def _get():
            backboard = BackboardService()
            meeting_svc = MeetingService(backboard)
            return await meeting_svc.get_meeting(thread_id)

        meeting = run_async(_get())
        if not meeting:
            return jsonify({"error": "Meeting not found"}), 404

        return jsonify(meeting), 200
    except Exception as e:
        current_app.logger.exception("Error getting meeting")
        return jsonify({"error": str(e)}), 500


@meetings_bp.route("/customers/<assistant_id>/meetings", methods=["GET"])
def get_customer_meetings(assistant_id: str):
    """Get all meetings for a customer.

    Args:
        assistant_id: The customer's assistant ID

    Query params:
        limit: Maximum number to return (default 20)

    Returns:
        JSON array of meeting summaries
    """
    try:
        limit = request.args.get("limit", 20, type=int)

        async def _get():
            backboard = BackboardService()
            meeting_svc = MeetingService(backboard)
            return await meeting_svc.get_customer_meetings(assistant_id, limit=limit)

        meetings = run_async(_get())
        return jsonify({"meetings": meetings}), 200
    except Exception as e:
        current_app.logger.exception("Error getting meetings")
        return jsonify({"error": str(e)}), 500


@meetings_bp.route("/customers/<assistant_id>/meetings/<thread_id>", methods=["DELETE"])
def delete_meeting(assistant_id: str, thread_id: str):
    """Delete a meeting by thread ID.

    Args:
        assistant_id: The customer's assistant ID
        thread_id: The meeting thread ID

    Returns:
        JSON with success status
    """
    try:
        async def _delete():
            backboard = BackboardService()
            meeting_svc = MeetingService(backboard)
            return await meeting_svc.delete_meeting(assistant_id, thread_id)

        deleted = run_async(_delete())
        if not deleted:
            return jsonify({"error": "Meeting not found"}), 404

        return jsonify({"success": True}), 200
    except Exception as e:
        current_app.logger.exception("Error deleting meeting")
        return jsonify({"error": str(e)}), 500


@meetings_bp.route("/customers/<assistant_id>/meetings/<thread_id>/labels", methods=["PATCH"])
def update_meeting_labels(assistant_id: str, thread_id: str):
    """Update labels for a meeting.

    Args:
        assistant_id: The customer's assistant ID
        thread_id: The meeting thread ID

    Request body:
        labels: List of label strings

    Returns:
        JSON with updated meeting data
    """
    try:
        data = request.get_json()
        labels = data.get("labels", [])

        if not isinstance(labels, list):
            return jsonify({"error": "labels must be a list"}), 400

        async def _update():
            backboard = BackboardService()
            meeting_svc = MeetingService(backboard)
            return await meeting_svc.update_meeting_labels(assistant_id, thread_id, labels)

        meeting = run_async(_update())
        if not meeting:
            return jsonify({"error": "Meeting not found"}), 404

        return jsonify(meeting), 200
    except Exception as e:
        current_app.logger.exception("Error updating meeting labels")
        return jsonify({"error": str(e)}), 500


@meetings_bp.route("/customers/<assistant_id>/products", methods=["GET"])
def get_customer_products(assistant_id: str):
    """Get all products discussed for a customer.

    Args:
        assistant_id: The customer's assistant ID

    Returns:
        JSON with list of products
    """
    try:
        async def _get():
            backboard = BackboardService()
            meeting_svc = MeetingService(backboard)
            return await meeting_svc.get_all_products(assistant_id)

        products = run_async(_get())
        return jsonify({"products": products}), 200
    except Exception as e:
        current_app.logger.exception("Error getting products")
        return jsonify({"error": str(e)}), 500


@meetings_bp.route("/customers/<assistant_id>/products", methods=["PATCH"])
def rename_product(assistant_id: str):
    """Rename a product across all meetings for a customer.

    Args:
        assistant_id: The customer's assistant ID

    Request body:
        old_name: The current product name
        new_name: The new product name

    Returns:
        JSON with updated list of products
    """
    try:
        data = request.get_json()
        old_name = data.get("old_name", "").strip()
        new_name = data.get("new_name", "").strip()

        if not old_name:
            return jsonify({"error": "old_name is required"}), 400
        if not new_name:
            return jsonify({"error": "new_name is required"}), 400

        async def _rename():
            backboard = BackboardService()
            meeting_svc = MeetingService(backboard)
            return await meeting_svc.rename_product_across_meetings(assistant_id, old_name, new_name)

        products = run_async(_rename())
        return jsonify({"products": products}), 200
    except Exception as e:
        current_app.logger.exception("Error renaming product")
        return jsonify({"error": str(e)}), 500


@meetings_bp.route("/customers/<assistant_id>/products/<path:product_name>", methods=["DELETE"])
def delete_product(assistant_id: str, product_name: str):
    """Delete a product from all meetings for a customer.

    Args:
        assistant_id: The customer's assistant ID
        product_name: The product name to delete (URL encoded)

    Returns:
        JSON with updated list of products
    """
    try:
        async def _delete():
            backboard = BackboardService()
            meeting_svc = MeetingService(backboard)
            return await meeting_svc.delete_product_across_meetings(assistant_id, product_name)

        products = run_async(_delete())
        return jsonify({"products": products}), 200
    except Exception as e:
        current_app.logger.exception("Error deleting product")
        return jsonify({"error": str(e)}), 500
