"""Customer API endpoints."""

import asyncio
from flask import Blueprint, request, jsonify, current_app, session

from app.schemas.crm import CustomerCreate
from app.schemas.enums import CustomerSize
from app.services.backboard import BackboardService
from app.services.orchestrator import OrchestratorService
from app.services.customer import CustomerService
from app.services.user import UserService
from app.services.auth import get_current_user, login_required, manager_required

customers_bp = Blueprint("customers", __name__)


def run_async(coro):
    """Run an async coroutine in a sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _list_customers():
    """Get all customers."""
    backboard = BackboardService()
    orchestrator = OrchestratorService(backboard)
    customer_svc = CustomerService(backboard)

    await orchestrator.ensure_orchestrator_exists()

    # Get customer registry from orchestrator
    registry = await orchestrator.get_all_customers()

    customers = []
    for entry in registry:
        customer = await customer_svc.get_customer(entry["assistant_id"])
        if customer:
            customers.append(customer.model_dump(mode="json"))

    return customers


async def _get_customer(assistant_id: str):
    """Get a customer with full details."""
    backboard = BackboardService()
    customer_svc = CustomerService(backboard)

    summary = await customer_svc.get_customer_summary(assistant_id)
    return summary


async def _create_customer(data: CustomerCreate):
    """Create a new customer."""
    backboard = BackboardService()
    orchestrator = OrchestratorService(backboard)
    customer_svc = CustomerService(backboard)

    await orchestrator.ensure_orchestrator_exists()

    # Check if customer already exists
    existing_id, is_new = await orchestrator.find_or_create_customer(
        company_name=data.company_name,
        company_domain=data.domain,
    )

    if not is_new:
        customer = await customer_svc.get_customer(existing_id)
        return customer.model_dump(mode="json") if customer else None, False

    # Create new customer
    customer = await customer_svc.create_customer(
        company_name=data.company_name,
        company_domain=data.domain,
        industry=data.industry,
        size=data.size,
    )

    # Register with orchestrator
    await orchestrator.register_customer(data.company_name, customer.assistant_id)

    return customer.model_dump(mode="json"), True


async def _delete_customer(assistant_id: str):
    """Delete a customer and unregister from orchestrator."""
    backboard = BackboardService()
    orchestrator = OrchestratorService(backboard)
    customer_svc = CustomerService(backboard)

    await orchestrator.ensure_orchestrator_exists()
    customer = await customer_svc.get_customer(assistant_id)

    await orchestrator.unregister_customer(assistant_id)
    await backboard.delete_assistant(assistant_id)

    return customer


async def _update_customer(assistant_id: str, updates: dict):
    """Update a customer's information."""
    backboard = BackboardService()
    orchestrator = OrchestratorService(backboard)
    customer_svc = CustomerService(backboard)

    await orchestrator.ensure_orchestrator_exists()

    # Get existing customer to check for company name changes
    old_customer = await customer_svc.get_customer(assistant_id)
    old_name = old_customer.company_name if old_customer else None

    # Handle size enum conversion
    if "size" in updates and updates["size"]:
        try:
            updates["size"] = CustomerSize(updates["size"])
        except ValueError:
            updates["size"] = None

    updated = await customer_svc.update_customer(assistant_id, **updates)

    # If company name changed, update the orchestrator registry
    if updated and "company_name" in updates and updates["company_name"] != old_name:
        await orchestrator.unregister_customer(assistant_id)
        await orchestrator.register_customer(updates["company_name"], assistant_id)

    return updated


@customers_bp.route("/customers", methods=["GET"])
@login_required
def list_customers():
    """List all customers.

    Returns:
        JSON array of customers
    """
    try:
        customers = run_async(_list_customers())
        return jsonify({"customers": customers}), 200
    except Exception as e:
        current_app.logger.exception("Error listing customers")
        return jsonify({"error": str(e)}), 500


@customers_bp.route("/customers/<assistant_id>", methods=["GET"])
@login_required
def get_customer(assistant_id: str):
    """Get a customer by assistant ID.

    Args:
        assistant_id: The customer's Backboard assistant ID

    Returns:
        JSON with customer details, contacts, opportunities, activities
    """
    try:
        summary = run_async(_get_customer(assistant_id))
        if not summary.get("customer"):
            return jsonify({"error": "Customer not found"}), 404
        return jsonify(summary), 200
    except Exception as e:
        current_app.logger.exception("Error getting customer")
        return jsonify({"error": str(e)}), 500


@customers_bp.route("/customers/<assistant_id>", methods=["DELETE"])
@manager_required
def delete_customer(assistant_id: str):
    """Delete a customer and all related data (manager only)."""
    try:
        customer = run_async(_delete_customer(assistant_id))
        return jsonify({
            "deleted": True,
            "customer": customer.model_dump(mode="json") if customer else None,
        }), 200
    except Exception as e:
        current_app.logger.exception("Error deleting customer")
        return jsonify({"error": str(e)}), 500


@customers_bp.route("/customers/<assistant_id>", methods=["PATCH"])
@login_required
def update_customer(assistant_id: str):
    """Update a customer's information.

    Args:
        assistant_id: The customer's Backboard assistant ID

    Request body (all fields optional):
        {
            "company_name": "New Name",
            "domain": "newdomain.com",
            "industry": "FinTech",
            "size": "enterprise"
        }

    Returns:
        JSON with updated customer
    """
    try:
        json_data = request.get_json()
        if not json_data:
            return jsonify({"error": "Request body is required"}), 400

        # Only allow specific fields to be updated
        allowed_fields = {"company_name", "domain", "industry", "size"}
        updates = {k: v for k, v in json_data.items() if k in allowed_fields}

        if not updates:
            return jsonify({"error": "No valid fields to update"}), 400

        updated = run_async(_update_customer(assistant_id, updates))

        if not updated:
            return jsonify({"error": "Customer not found"}), 404

        return jsonify({"customer": updated.model_dump(mode="json")}), 200

    except Exception as e:
        current_app.logger.exception("Error updating customer")
        return jsonify({"error": str(e)}), 500


@customers_bp.route("/customers", methods=["POST"])
@login_required
def create_customer():
    """Create a new customer.

    Request body:
        {
            "company_name": "Acme Corp",
            "domain": "acme.com",
            "industry": "SaaS",
            "size": "mid_market"
        }

    Returns:
        JSON with created customer
    """
    try:
        json_data = request.get_json()
        if not json_data:
            return jsonify({"error": "Request body is required"}), 400

        # Parse request
        try:
            data = CustomerCreate.model_validate(json_data)
        except Exception as e:
            return jsonify({"error": f"Invalid request: {str(e)}"}), 400

        customer_data, is_new = run_async(_create_customer(data))

        if not customer_data:
            return jsonify({"error": "Failed to create customer"}), 500

        status_code = 201 if is_new else 200
        return jsonify({
            "customer": customer_data,
            "is_new": is_new,
        }), status_code

    except Exception as e:
        current_app.logger.exception("Error creating customer")
        return jsonify({"error": str(e)}), 500


@customers_bp.route("/customers/<assistant_id>/contacts", methods=["GET"])
@login_required
def get_customer_contacts(assistant_id: str):
    """Get all contacts for a customer.

    Args:
        assistant_id: The customer's assistant ID

    Returns:
        JSON array of contacts
    """
    try:
        async def _get_contacts():
            backboard = BackboardService()
            customer_svc = CustomerService(backboard)
            contacts = await customer_svc.get_contacts(assistant_id)
            return [c.model_dump(mode="json") for c in contacts]

        contacts = run_async(_get_contacts())
        return jsonify({"contacts": contacts}), 200
    except Exception as e:
        current_app.logger.exception("Error getting contacts")
        return jsonify({"error": str(e)}), 500


@customers_bp.route("/customers/<assistant_id>/opportunities", methods=["GET"])
@login_required
def get_customer_opportunities(assistant_id: str):
    """Get all opportunities for a customer.

    Args:
        assistant_id: The customer's assistant ID

    Returns:
        JSON array of opportunities
    """
    try:
        async def _get_opportunities():
            backboard = BackboardService()
            customer_svc = CustomerService(backboard)
            opportunities = await customer_svc.get_opportunities(assistant_id)
            return [o.model_dump(mode="json") for o in opportunities]

        opportunities = run_async(_get_opportunities())
        return jsonify({"opportunities": opportunities}), 200
    except Exception as e:
        current_app.logger.exception("Error getting opportunities")
        return jsonify({"error": str(e)}), 500


@customers_bp.route("/customers/<assistant_id>/activities", methods=["GET"])
@login_required
def get_customer_activities(assistant_id: str):
    """Get activities for a customer.

    Args:
        assistant_id: The customer's assistant ID

    Query params:
        limit: Maximum number to return (default 20)

    Returns:
        JSON array of activities
    """
    try:
        limit = request.args.get("limit", 20, type=int)

        async def _get_activities():
            backboard = BackboardService()
            customer_svc = CustomerService(backboard)
            activities = await customer_svc.get_activities(assistant_id)
            return [a.model_dump(mode="json") for a in activities[:limit]]

        activities = run_async(_get_activities())
        return jsonify({"activities": activities}), 200
    except Exception as e:
        current_app.logger.exception("Error getting activities")
        return jsonify({"error": str(e)}), 500


@customers_bp.route("/dashboard", methods=["GET"])
@login_required
def get_dashboard_data():
    """Get dashboard data for async loading.

    Returns:
        JSON with customers, stats, and today's follow-ups
    """
    try:
        # Get current user for filtering
        current_user = get_current_user()
        is_manager = current_user and current_user.is_manager()
        user_id = current_user.id if current_user else None

        async def _get_data():
            backboard = BackboardService()
            orchestrator = OrchestratorService(backboard)
            customer_svc = CustomerService(backboard)

            await orchestrator.ensure_orchestrator_exists()

            # Get all customers with basic info
            registry = await orchestrator.get_all_customers()
            customers = []

            for entry in registry:
                customer = await customer_svc.get_customer(entry["assistant_id"])
                if customer:
                    # Filter by assignment for non-managers
                    if not is_manager and customer.assigned_user_id != user_id:
                        continue

                    opportunities = await customer_svc.get_opportunities(entry["assistant_id"])
                    activities = await customer_svc.get_activities(entry["assistant_id"])

                    customers.append({
                        "customer": customer.model_dump(mode="json"),
                        "opportunity_count": len(opportunities),
                        "activity_count": len(activities),
                        "last_activity": activities[0].date.isoformat() if activities else None,
                    })

            # Get customers with follow-ups due today (filtered for non-managers)
            todays_followups = await customer_svc.get_customers_with_followups_today(
                registry, assigned_user_id=None if is_manager else user_id
            )

            return customers, todays_followups

        customers, todays_followups = run_async(_get_data())

        return jsonify({
            "customers": customers,
            "customer_count": len(customers),
            "todays_followups": todays_followups,
        }), 200

    except Exception as e:
        current_app.logger.exception("Error getting dashboard data")
        return jsonify({"error": str(e)}), 500


@customers_bp.route("/customers/<assistant_id>/assign", methods=["POST"])
@manager_required
def assign_customer(assistant_id: str):
    """Assign a customer to a user (manager only).

    Request body:
        {"user_id": "user-uuid" or null}

    Returns:
        JSON with updated customer
    """
    try:
        json_data = request.get_json()
        user_id = json_data.get("user_id") if json_data else None

        async def _assign():
            backboard = BackboardService()
            customer_svc = CustomerService(backboard)
            return await customer_svc.assign_customer(assistant_id, user_id)

        updated = run_async(_assign())

        if not updated:
            return jsonify({"error": "Customer not found"}), 404

        return jsonify({"customer": updated.model_dump(mode="json")}), 200

    except Exception as e:
        current_app.logger.exception("Error assigning customer")
        return jsonify({"error": str(e)}), 500


@customers_bp.route("/manager/dashboard", methods=["GET"])
@manager_required
def get_manager_dashboard():
    """Get manager dashboard data with all users and customers.

    Returns:
        JSON with users, customers, and aggregate stats
    """
    try:
        async def _get_data():
            backboard = BackboardService()
            orchestrator = OrchestratorService(backboard)
            customer_svc = CustomerService(backboard)
            user_svc = UserService(backboard)

            await orchestrator.ensure_orchestrator_exists()

            # Get all users
            users = await user_svc.list_users()

            # Get all customers
            registry = await orchestrator.get_all_customers()
            customers = []
            total_opportunities = 0
            total_activities = 0

            # Build user stats
            user_stats = {u.id: {"customer_count": 0, "opportunity_count": 0, "activity_count": 0} for u in users}

            for entry in registry:
                customer = await customer_svc.get_customer(entry["assistant_id"])
                if customer:
                    opportunities = await customer_svc.get_opportunities(entry["assistant_id"])
                    activities = await customer_svc.get_activities(entry["assistant_id"])

                    opp_count = len(opportunities)
                    act_count = len(activities)
                    total_opportunities += opp_count
                    total_activities += act_count

                    customers.append({
                        "customer": customer.model_dump(mode="json"),
                        "opportunity_count": opp_count,
                        "activity_count": act_count,
                    })

                    # Update user stats
                    if customer.assigned_user_id and customer.assigned_user_id in user_stats:
                        user_stats[customer.assigned_user_id]["customer_count"] += 1
                        user_stats[customer.assigned_user_id]["opportunity_count"] += opp_count
                        user_stats[customer.assigned_user_id]["activity_count"] += act_count

            # Build user list with stats
            user_list = []
            for user in users:
                stats = user_stats.get(user.id, {})
                user_list.append({
                    "id": user.id,
                    "email": user.email,
                    "name": user.name,
                    "role": user.role.value,
                    "customer_count": stats.get("customer_count", 0),
                    "opportunity_count": stats.get("opportunity_count", 0),
                    "activity_count": stats.get("activity_count", 0),
                })

            return {
                "users": user_list,
                "customers": customers,
                "user_count": len(users),
                "customer_count": len(customers),
                "opportunity_count": total_opportunities,
                "activity_count": total_activities,
            }

        data = run_async(_get_data())
        return jsonify(data), 200

    except Exception as e:
        current_app.logger.exception("Error getting manager dashboard data")
        return jsonify({"error": str(e)}), 500
