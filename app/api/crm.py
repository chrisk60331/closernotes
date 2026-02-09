"""CRM object API endpoints."""

import asyncio
from datetime import date
from flask import Blueprint, request, jsonify, current_app

from app.schemas.crm import ContactCreate, OpportunityCreate, OpportunityUpdate
from app.services.backboard import BackboardService
from app.services.crm import CRMService
from app.services.customer import CustomerService
from app.services.cache_store import CacheStoreService

crm_bp = Blueprint("crm", __name__)


def run_async(coro):
    """Run an async coroutine in a sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# Contact endpoints
@crm_bp.route("/customers/<assistant_id>/contacts", methods=["POST"])
def create_contact(assistant_id: str):
    """Create a new contact for a customer.

    Args:
        assistant_id: The customer's assistant ID

    Request body:
        {
            "customer_id": "customer-uuid",
            "name": "John Smith",
            "email": "john@acme.com",
            "phone": "+1 555-123-4567",
            "role": "VP Engineering",
            "is_champion": true,
            "is_decision_maker": false,
            "preferred_contact_method": "email"  // email, text, call, whatsapp
        }

    Returns:
        JSON with created contact
    """
    try:
        json_data = request.get_json()
        if not json_data:
            return jsonify({"error": "Request body is required"}), 400

        try:
            data = ContactCreate.model_validate(json_data)
        except Exception as e:
            return jsonify({"error": f"Invalid request: {str(e)}"}), 400

        async def _create():
            backboard = BackboardService()
            crm_svc = CRMService(backboard)
            result = await crm_svc.create_contact(assistant_id, data)
            await CacheStoreService(backboard).update_customer_summary(assistant_id)
            return result

        contact = run_async(_create())
        return jsonify({"contact": contact.model_dump(mode="json")}), 201

    except Exception as e:
        current_app.logger.exception("Error creating contact")
        return jsonify({"error": str(e)}), 500


@crm_bp.route("/customers/<assistant_id>/contacts/<contact_id>", methods=["GET"])
def get_contact(assistant_id: str, contact_id: str):
    """Get a contact by ID.

    Args:
        assistant_id: The customer's assistant ID
        contact_id: The contact ID

    Returns:
        JSON with contact details
    """
    try:
        async def _get():
            backboard = BackboardService()
            crm_svc = CRMService(backboard)
            return await crm_svc.get_contact(assistant_id, contact_id)

        contact = run_async(_get())
        if not contact:
            return jsonify({"error": "Contact not found"}), 404

        return jsonify({"contact": contact.model_dump(mode="json")}), 200

    except Exception as e:
        current_app.logger.exception("Error getting contact")
        return jsonify({"error": str(e)}), 500


@crm_bp.route("/customers/<assistant_id>/contacts/<contact_id>", methods=["PATCH"])
def update_contact(assistant_id: str, contact_id: str):
    """Update a contact.

    Args:
        assistant_id: The customer's assistant ID
        contact_id: The contact ID

    Request body:
        Fields to update (partial update supported)

    Returns:
        JSON with updated contact
    """
    try:
        json_data = request.get_json()
        if not json_data:
            return jsonify({"error": "Request body is required"}), 400

        async def _update():
            backboard = BackboardService()
            crm_svc = CRMService(backboard)
            result = await crm_svc.update_contact(assistant_id, contact_id, **json_data)
            if result:
                await CacheStoreService(backboard).update_customer_summary(assistant_id)
            return result

        contact = run_async(_update())
        if not contact:
            return jsonify({"error": "Contact not found"}), 404

        return jsonify({"contact": contact.model_dump(mode="json")}), 200

    except Exception as e:
        current_app.logger.exception("Error updating contact")
        return jsonify({"error": str(e)}), 500


@crm_bp.route("/customers/<assistant_id>/contacts/<contact_id>", methods=["DELETE"])
def delete_contact(assistant_id: str, contact_id: str):
    """Delete a contact.

    Args:
        assistant_id: The customer's assistant ID
        contact_id: The contact ID

    Returns:
        Empty response on success
    """
    try:
        async def _delete():
            backboard = BackboardService()
            crm_svc = CRMService(backboard)
            result = await crm_svc.delete_contact(assistant_id, contact_id)
            if result:
                await CacheStoreService(backboard).update_customer_summary(assistant_id)
            return result

        deleted = run_async(_delete())
        if not deleted:
            return jsonify({"error": "Contact not found"}), 404

        return "", 204

    except Exception as e:
        current_app.logger.exception("Error deleting contact")
        return jsonify({"error": str(e)}), 500


# Opportunity endpoints
@crm_bp.route("/customers/<assistant_id>/opportunities", methods=["POST"])
def create_opportunity(assistant_id: str):
    """Create a new opportunity for a customer.

    Args:
        assistant_id: The customer's assistant ID

    Request body:
        {
            "customer_id": "customer-uuid",
            "name": "Enterprise License Deal",
            "stage": "discovery",
            "value": 50000,
            "close_date_estimate": "2024-06-30",
            "confidence": 60,
            "competitors": ["Competitor A"]
        }

    Returns:
        JSON with created opportunity
    """
    try:
        json_data = request.get_json()
        if not json_data:
            return jsonify({"error": "Request body is required"}), 400

        try:
            data = OpportunityCreate.model_validate(json_data)
        except Exception as e:
            return jsonify({"error": f"Invalid request: {str(e)}"}), 400

        async def _create():
            backboard = BackboardService()
            crm_svc = CRMService(backboard)
            result = await crm_svc.create_opportunity(assistant_id, data)
            await CacheStoreService(backboard).update_customer_summary(assistant_id)
            return result

        opportunity = run_async(_create())
        return jsonify({"opportunity": opportunity.model_dump(mode="json")}), 201

    except Exception as e:
        current_app.logger.exception("Error creating opportunity")
        return jsonify({"error": str(e)}), 500


@crm_bp.route("/customers/<assistant_id>/opportunities/<opportunity_id>", methods=["GET"])
def get_opportunity(assistant_id: str, opportunity_id: str):
    """Get an opportunity by ID.

    Args:
        assistant_id: The customer's assistant ID
        opportunity_id: The opportunity ID

    Returns:
        JSON with opportunity details
    """
    try:
        async def _get():
            backboard = BackboardService()
            crm_svc = CRMService(backboard)
            return await crm_svc.get_opportunity(assistant_id, opportunity_id)

        opportunity = run_async(_get())
        if not opportunity:
            return jsonify({"error": "Opportunity not found"}), 404

        return jsonify({"opportunity": opportunity.model_dump(mode="json")}), 200

    except Exception as e:
        current_app.logger.exception("Error getting opportunity")
        return jsonify({"error": str(e)}), 500


@crm_bp.route("/customers/<assistant_id>/opportunities/<opportunity_id>", methods=["PATCH"])
def update_opportunity(assistant_id: str, opportunity_id: str):
    """Update an opportunity.

    Args:
        assistant_id: The customer's assistant ID
        opportunity_id: The opportunity ID

    Request body:
        Fields to update (partial update supported)

    Returns:
        JSON with updated opportunity
    """
    try:
        json_data = request.get_json()
        if not json_data:
            return jsonify({"error": "Request body is required"}), 400

        try:
            data = OpportunityUpdate.model_validate(json_data)
        except Exception as e:
            return jsonify({"error": f"Invalid request: {str(e)}"}), 400

        async def _update():
            backboard = BackboardService()
            crm_svc = CRMService(backboard)
            result = await crm_svc.update_opportunity(assistant_id, opportunity_id, data)
            if result:
                await CacheStoreService(backboard).update_customer_summary(assistant_id)
            return result

        opportunity = run_async(_update())
        if not opportunity:
            return jsonify({"error": "Opportunity not found"}), 404

        return jsonify({"opportunity": opportunity.model_dump(mode="json")}), 200

    except Exception as e:
        current_app.logger.exception("Error updating opportunity")
        return jsonify({"error": str(e)}), 500


@crm_bp.route("/customers/<assistant_id>/opportunities/<opportunity_id>", methods=["DELETE"])
def delete_opportunity(assistant_id: str, opportunity_id: str):
    """Delete an opportunity.

    Args:
        assistant_id: The customer's assistant ID
        opportunity_id: The opportunity ID

    Returns:
        Empty response on success
    """
    try:
        async def _delete():
            backboard = BackboardService()
            crm_svc = CRMService(backboard)
            result = await crm_svc.delete_opportunity(assistant_id, opportunity_id)
            if result:
                await CacheStoreService(backboard).update_customer_summary(assistant_id)
            return result

        deleted = run_async(_delete())
        if not deleted:
            return jsonify({"error": "Opportunity not found"}), 404

        return "", 204

    except Exception as e:
        current_app.logger.exception("Error deleting opportunity")
        return jsonify({"error": str(e)}), 500


# Action items endpoint
@crm_bp.route("/customers/<assistant_id>/action-items", methods=["GET"])
def get_pending_action_items(assistant_id: str):
    """Get pending action items for a customer.

    Args:
        assistant_id: The customer's assistant ID

    Returns:
        JSON array of pending action items
    """
    try:
        async def _get():
            backboard = BackboardService()
            crm_svc = CRMService(backboard)
            return await crm_svc.get_pending_action_items(assistant_id)

        action_items = run_async(_get())
        return jsonify({"action_items": action_items}), 200

    except Exception as e:
        current_app.logger.exception("Error getting action items")
        return jsonify({"error": str(e)}), 500


# Customer follow-up endpoints
@crm_bp.route("/customers/<assistant_id>/followup", methods=["GET"])
def get_customer_followup(assistant_id: str):
    """Get the next follow-up date for a customer.

    If not explicitly set, calculates 2 weeks from last activity.

    Args:
        assistant_id: The customer's assistant ID

    Returns:
        JSON with next_followup_date (may be null if no activities)
    """
    try:
        async def _get():
            backboard = BackboardService()
            customer_svc = CustomerService(backboard)
            return await customer_svc.get_customer_next_followup(assistant_id)

        followup_date = run_async(_get())
        return jsonify({
            "next_followup_date": followup_date.isoformat() if followup_date else None,
        }), 200

    except Exception as e:
        current_app.logger.exception("Error getting follow-up date")
        return jsonify({"error": str(e)}), 500


@crm_bp.route("/customers/<assistant_id>/followup", methods=["PUT"])
def set_customer_followup(assistant_id: str):
    """Set the next follow-up date for a customer.

    Args:
        assistant_id: The customer's assistant ID

    Request body:
        {
            "next_followup_date": "2024-03-15"  // ISO date or null to clear
        }

    Returns:
        JSON with updated customer
    """
    try:
        json_data = request.get_json()
        if json_data is None:
            return jsonify({"error": "Request body is required"}), 400

        followup_str = json_data.get("next_followup_date")
        followup_date = None
        if followup_str:
            try:
                followup_date = date.fromisoformat(followup_str)
            except ValueError:
                return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

        async def _set():
            backboard = BackboardService()
            customer_svc = CustomerService(backboard)
            result = await customer_svc.set_customer_followup_date(assistant_id, followup_date)
            if result:
                await CacheStoreService(backboard).update_customer_summary(assistant_id)
            return result

        customer = run_async(_set())
        if not customer:
            return jsonify({"error": "Customer not found"}), 404

        return jsonify({"customer": customer.model_dump(mode="json")}), 200

    except Exception as e:
        current_app.logger.exception("Error setting follow-up date")
        return jsonify({"error": str(e)}), 500
