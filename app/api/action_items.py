"""Action Items API endpoints."""

import asyncio
from datetime import date
from flask import Blueprint, request, jsonify, current_app

from app.schemas.crm import PromotedActionItemUpdate
from app.services.backboard import BackboardService
from app.services.crm import CRMService
from app.services.cache_store import CacheStoreService

action_items_bp = Blueprint("action_items", __name__)


def run_async(coro):
    """Run an async coroutine in a sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@action_items_bp.route("/action-items/<assistant_id>", methods=["POST"])
def create_action_item(assistant_id: str):
    """Create a new manual action item.

    Request body:
        {
            "description": "What needs to be done",
            "owner": "Optional owner name",
            "due_date": "Optional YYYY-MM-DD"
        }

    Returns:
        Created action item or error
    """
    try:
        json_data = request.get_json() or {}

        if not json_data.get("description"):
            return jsonify({"error": "Description is required"}), 400

        async def _create():
            from app.services.customer import CustomerService

            backboard = BackboardService()
            customer_svc = CustomerService(backboard)
            crm_svc = CRMService(backboard)

            # Get customer to get customer_id
            customer = await customer_svc.get_customer(assistant_id)
            if not customer:
                return None, "Customer not found"

            # Parse due_date if provided
            due_date_val = None
            if json_data.get("due_date"):
                try:
                    due_date_val = date.fromisoformat(json_data["due_date"])
                except ValueError:
                    pass

            # Create action item with placeholder activity/thread IDs for manual items
            action_item = await crm_svc.create_promoted_action_item(
                assistant_id=assistant_id,
                customer_id=customer.id,
                activity_id="manual",
                thread_id="manual",
                description=json_data["description"],
                owner=json_data.get("owner"),
                due_date=due_date_val,
                source_excerpt=None,
            )

            await CacheStoreService(backboard).update_customer_summary(assistant_id)
            return action_item, None

        action_item, error = run_async(_create())

        if error:
            return jsonify({"error": error}), 404

        return jsonify(action_item.model_dump(mode="json")), 201

    except Exception as e:
        current_app.logger.exception("Error creating action item")
        return jsonify({"error": str(e)}), 500


@action_items_bp.route("/action-items/<assistant_id>/<action_item_id>", methods=["PATCH"])
def update_action_item(assistant_id: str, action_item_id: str):
    """Update a promoted action item.

    Request body (all fields optional):
        {
            "description": "Updated description",
            "owner": "New owner",
            "is_completed": true
        }

    Returns:
        Updated action item or error
    """
    try:
        json_data = request.get_json() or {}

        async def _update():
            backboard = BackboardService()
            crm_svc = CRMService(backboard)

            # Validate and parse update data
            update_data = PromotedActionItemUpdate.model_validate(json_data)

            # Update the action item
            updated = await crm_svc.update_promoted_action_item(
                assistant_id=assistant_id,
                action_item_id=action_item_id,
                data=update_data,
            )

            if updated:
                await CacheStoreService(backboard).update_customer_summary(assistant_id)
            return updated

        updated = run_async(_update())

        if not updated:
            return jsonify({"error": "Action item not found"}), 404

        return jsonify(updated.model_dump(mode="json")), 200

    except Exception as e:
        current_app.logger.exception("Error updating action item")
        return jsonify({"error": str(e)}), 500


@action_items_bp.route("/action-items/<assistant_id>/<action_item_id>", methods=["DELETE"])
def dismiss_action_item(assistant_id: str, action_item_id: str):
    """Dismiss (soft delete) a promoted action item.

    Returns:
        Dismissed action item or error
    """
    try:
        async def _dismiss():
            backboard = BackboardService()
            crm_svc = CRMService(backboard)

            dismissed = await crm_svc.dismiss_promoted_action_item(
                assistant_id=assistant_id,
                action_item_id=action_item_id,
            )

            if dismissed:
                await CacheStoreService(backboard).update_customer_summary(assistant_id)
            return dismissed

        dismissed = run_async(_dismiss())

        if not dismissed:
            return jsonify({"error": "Action item not found"}), 404

        return jsonify({"status": "dismissed", "id": action_item_id}), 200

    except Exception as e:
        current_app.logger.exception("Error dismissing action item")
        return jsonify({"error": str(e)}), 500


@action_items_bp.route("/action-items/<assistant_id>/<action_item_id>/toggle", methods=["POST"])
def toggle_action_item(assistant_id: str, action_item_id: str):
    """Toggle the completion status of an action item.

    Returns:
        Updated action item with new completion status
    """
    try:
        async def _toggle():
            backboard = BackboardService()
            crm_svc = CRMService(backboard)

            # First get the current item
            item = await crm_svc.get_promoted_action_item(assistant_id, action_item_id)
            if not item:
                return None

            # Toggle the completion status
            update_data = PromotedActionItemUpdate(is_completed=not item.is_completed)
            updated = await crm_svc.update_promoted_action_item(
                assistant_id=assistant_id,
                action_item_id=action_item_id,
                data=update_data,
            )

            if updated:
                await CacheStoreService(backboard).update_customer_summary(assistant_id)
            return updated

        updated = run_async(_toggle())

        if not updated:
            return jsonify({"error": "Action item not found"}), 404

        return jsonify(updated.model_dump(mode="json")), 200

    except Exception as e:
        current_app.logger.exception("Error toggling action item")
        return jsonify({"error": str(e)}), 500


@action_items_bp.route("/action-items/<assistant_id>/backfill", methods=["POST"])
def backfill_action_items(assistant_id: str):
    """Backfill promoted action items from existing activities.

    This migrates embedded action items to standalone records.

    Returns:
        Count of items backfilled
    """
    try:
        async def _backfill():
            from app.services.customer import CustomerService
            
            backboard = BackboardService()
            customer_svc = CustomerService(backboard)
            crm_svc = CRMService(backboard)

            # Get customer to get customer_id
            customer = await customer_svc.get_customer(assistant_id)
            if not customer:
                return None, "Customer not found"

            count = await crm_svc.backfill_promoted_action_items(
                assistant_id=assistant_id,
                customer_id=customer.id,
            )

            if count and count > 0:
                await CacheStoreService(backboard).update_customer_summary(assistant_id)
            return count, None

        count, error = run_async(_backfill())

        if error:
            return jsonify({"error": error}), 404

        return jsonify({"status": "success", "backfilled": count}), 200

    except Exception as e:
        current_app.logger.exception("Error backfilling action items")
        return jsonify({"error": str(e)}), 500
