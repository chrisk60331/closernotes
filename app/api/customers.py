"""Customer API endpoints."""

import asyncio
import json
from flask import Blueprint, request, jsonify, current_app, session

from app.schemas.crm import CustomerCreate
from app.schemas.enums import CustomerSize
from app.services.backboard import BackboardService
from app.services.orchestrator import OrchestratorService
from app.services.customer import CustomerService
from app.services.user import UserService
from app.services.cache import CacheService, CACHE_TTLS, build_cache_key
from app.services.cache_store import CacheStoreService
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


async def _create_customer(data: CustomerCreate, assigned_user_id: str | None):
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
        if customer and assigned_user_id and customer.assigned_user_id is None:
            customer = await customer_svc.assign_customer(existing_id, assigned_user_id)
        return customer.model_dump(mode="json") if customer else None, False

    # Create new customer
    customer = await customer_svc.create_customer(
        company_name=data.company_name,
        company_domain=data.domain,
        industry=data.industry,
        size=data.size,
        assigned_user_id=assigned_user_id,
    )

    # Register with orchestrator
    await orchestrator.register_customer(data.company_name, customer.assistant_id)

    # Populate cache assistant
    cache_store = CacheStoreService(backboard)
    await cache_store.update_customer_summary(customer.assistant_id)

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

    # Remove from cache assistant
    cache_store = CacheStoreService(backboard)
    await cache_store.delete_customer_summary(assistant_id)

    return customer


async def _merge_customers(
    assistant_ids: list[str],
    company_name: str,
    domain: str | None,
    industry: str | None,
    size: CustomerSize | None,
    assigned_user_id: str | None,
):
    """Merge multiple customers into a brand-new customer.

    Creates a new customer, copies all non-customer memories from each
    source assistant (updating customer_id references), then deletes
    the source assistants and their registry/cache entries.

    Returns:
        The new Customer dict (JSON-serialisable).
    """
    backboard = BackboardService()
    orchestrator = OrchestratorService(backboard)
    customer_svc = CustomerService(backboard)
    cache_store = CacheStoreService(backboard)

    await orchestrator.ensure_orchestrator_exists()

    # --- 1. Create the merged customer --------------------------------
    new_customer = await customer_svc.create_customer(
        company_name=company_name,
        company_domain=domain,
        industry=industry,
        size=size,
        assigned_user_id=assigned_user_id,
    )
    await orchestrator.register_customer(company_name, new_customer.assistant_id)

    new_customer_id = new_customer.id
    new_assistant_id = new_customer.assistant_id

    # --- 2. Collect all memories from every source --------------------
    all_parsed: list[dict] = []       # (data_dict, is_json)
    raw_memories: list[str] = []      # non-JSON blobs

    for source_id in assistant_ids:
        try:
            memories = await backboard.get_memories(source_id)
        except Exception:
            continue  # source already gone — skip

        for memory in memories.memories:
            try:
                data = json.loads(memory.content)
            except (json.JSONDecodeError, ValueError):
                raw_memories.append(memory.content)
                continue

            # Skip the source's own Customer record
            if data.get("id") and data.get("company_name") and data.get("assistant_id"):
                continue

            # Update customer_id on entities that carry one
            if "customer_id" in data:
                data["customer_id"] = new_customer_id

            all_parsed.append(data)

    # --- 2b. Deduplicate contacts by case-insensitive name match ------
    contact_index: dict[str, dict] = {}   # lowered name -> merged dict
    non_contact_items: list[dict] = []

    for data in all_parsed:
        is_contact = (
            data.get("customer_id")
            and data.get("name")
            and "is_champion" in data
        )
        if not is_contact:
            non_contact_items.append(data)
            continue

        key = data["name"].strip().lower()
        if key not in contact_index:
            contact_index[key] = data
        else:
            # Merge: prefer non-null / truthy values from the duplicate
            existing = contact_index[key]
            for field in (
                "email", "phone", "role", "linkedin_url",
                "preferred_contact_method", "notes",
            ):
                if not existing.get(field) and data.get(field):
                    existing[field] = data[field]
            # Boolean flags: keep True if either is True
            for flag in ("is_champion", "is_decision_maker"):
                if data.get(flag):
                    existing[flag] = True
            # Keep earlier created_at
            if data.get("created_at", "") < existing.get("created_at", ""):
                existing["created_at"] = data["created_at"]
            # Keep later updated_at
            if data.get("updated_at", "") > existing.get("updated_at", ""):
                existing["updated_at"] = data["updated_at"]

    # --- 2c. Write everything to the new assistant --------------------
    for content in raw_memories:
        await backboard.add_memory(
            assistant_id=new_assistant_id,
            content=content,
        )

    for data in non_contact_items:
        await backboard.add_memory(
            assistant_id=new_assistant_id,
            content=json.dumps(data),
        )

    for data in contact_index.values():
        await backboard.add_memory(
            assistant_id=new_assistant_id,
            content=json.dumps(data),
        )

    # --- 3. Delete source customers -----------------------------------
    for source_id in assistant_ids:
        try:
            await orchestrator.unregister_customer(source_id)
            await backboard.delete_assistant(source_id)
            await cache_store.delete_customer_summary(source_id)
        except Exception:
            pass  # best-effort cleanup

    # --- 4. Refresh cache for the new customer ------------------------
    await cache_store.update_customer_summary(new_assistant_id)

    return new_customer.model_dump(mode="json")


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

    # Refresh cache
    if updated:
        cache_store = CacheStoreService(backboard)
        await cache_store.update_customer_summary(assistant_id)

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
@login_required
def delete_customer(assistant_id: str):
    """Delete a customer and all related data."""
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({"error": "Authentication required"}), 401

        async def _get_customer_for_access():
            backboard = BackboardService()
            customer_svc = CustomerService(backboard)
            return await customer_svc.get_customer(assistant_id)

        existing_customer = run_async(_get_customer_for_access())
        if not existing_customer:
            return jsonify({"error": "Customer not found"}), 404

        if not current_user.is_manager() and existing_customer.assigned_user_id != current_user.id:
            return jsonify({"error": "Not authorized to delete this customer"}), 403

        customer = run_async(_delete_customer(assistant_id)) or existing_customer
        return jsonify({
            "deleted": True,
            "customer": customer.model_dump(mode="json") if customer else None,
        }), 200
    except Exception as e:
        current_app.logger.exception("Error deleting customer")
        return jsonify({"error": str(e)}), 500


@customers_bp.route("/customers/merge", methods=["POST"])
@login_required
def merge_customers():
    """Merge two or more customers into a single new customer.

    Request body:
        {
            "assistant_ids": ["id1", "id2", ...],
            "company_name": "Merged Corp",
            "domain": "merged.com",   // optional
            "industry": "SaaS",       // optional
            "size": "mid_market"       // optional
        }

    Returns:
        JSON with the newly created merged customer
    """
    try:
        json_data = request.get_json()
        if not json_data:
            return jsonify({"error": "Request body is required"}), 400

        assistant_ids = json_data.get("assistant_ids", [])
        if not isinstance(assistant_ids, list) or len(assistant_ids) < 2:
            return jsonify({"error": "At least two assistant_ids are required"}), 400

        company_name = json_data.get("company_name")
        if not company_name:
            return jsonify({"error": "company_name is required"}), 400

        domain = json_data.get("domain")
        industry = json_data.get("industry")
        size_raw = json_data.get("size")
        size = None
        if size_raw:
            try:
                size = CustomerSize(size_raw)
            except ValueError:
                size = None

        # Permission check: user must have access to all source customers
        current_user = get_current_user()
        if not current_user:
            return jsonify({"error": "Authentication required"}), 401

        if not current_user.is_manager():
            async def _check_access():
                backboard = BackboardService()
                customer_svc = CustomerService(backboard)
                for aid in assistant_ids:
                    customer = await customer_svc.get_customer(aid)
                    if not customer:
                        return aid, "not_found"
                    if customer.assigned_user_id != current_user.id:
                        return aid, "forbidden"
                return None, None

            bad_id, reason = run_async(_check_access())
            if reason == "not_found":
                return jsonify({"error": f"Customer {bad_id} not found"}), 404
            if reason == "forbidden":
                return jsonify({"error": "Not authorized to merge all selected customers"}), 403

        assigned_user_id = current_user.id if current_user else None

        new_customer = run_async(_merge_customers(
            assistant_ids=assistant_ids,
            company_name=company_name,
            domain=domain,
            industry=industry,
            size=size,
            assigned_user_id=assigned_user_id,
        ))

        return jsonify({"customer": new_customer, "merged": True}), 201

    except Exception as e:
        current_app.logger.exception("Error merging customers")
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

        current_user = get_current_user()
        assigned_user_id = current_user.id if current_user else None
        customer_data, is_new = run_async(_create_customer(data, assigned_user_id))

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

    Reads from the cache assistant (single API call) then filters by
    the current user's permissions.

    Returns:
        JSON with customers, stats, and today's follow-ups
    """
    try:
        current_user = get_current_user()
        is_manager = current_user and current_user.is_manager()
        user_id = current_user.id if current_user else None

        async def _get_data():
            from datetime import date as date_type

            backboard = BackboardService()
            cache_store = CacheStoreService(backboard)
            cache = CacheService()

            role = "manager" if is_manager else "user"
            cache_key = build_cache_key("dashboard", role, user_id or "none")

            async def _build():
                summaries = await cache_store.get_all_summaries()

                # Permission filter
                if not is_manager:
                    summaries = [s for s in summaries if s.assigned_user_id == user_id]

                customers = []
                for s in summaries:
                    customers.append({
                        "customer": {
                            "id": s.customer_id,
                            "company_name": s.company_name,
                            "domain": s.domain,
                            "industry": s.industry,
                            "size": s.size,
                            "assistant_id": s.assistant_id,
                            "assigned_user_id": s.assigned_user_id,
                            "created_at": s.created_at.isoformat() if s.created_at else None,
                            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                            "next_followup_date": s.next_followup_date.isoformat() if s.next_followup_date else None,
                        },
                        "opportunity_count": s.opportunity_count,
                        "activity_count": s.activity_count,
                        "last_activity": s.last_activity_date.isoformat() if s.last_activity_date else None,
                    })

                today = date_type.today()
                todays_followups = []
                for s in summaries:
                    followup = s.next_followup_date
                    if followup and followup <= today:
                        todays_followups.append({
                            "customer": {
                                "id": s.customer_id,
                                "company_name": s.company_name,
                                "domain": s.domain,
                                "industry": s.industry,
                                "size": s.size,
                                "assistant_id": s.assistant_id,
                                "assigned_user_id": s.assigned_user_id,
                                "created_at": s.created_at.isoformat() if s.created_at else None,
                                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                                "next_followup_date": followup.isoformat(),
                            },
                            "followup_date": followup.isoformat(),
                            "is_overdue": followup < today,
                            "contact_count": s.contact_count,
                        })
                todays_followups.sort(key=lambda x: x["followup_date"])

                return {
                    "customers": customers,
                    "customer_count": len(customers),
                    "todays_followups": todays_followups,
                }

            return await cache.get_or_set(
                cache_key,
                cache.with_jitter(CACHE_TTLS["dashboard"]),
                _build,
                tags=["dashboards", "registry", f"user:{user_id or 'none'}", f"role:{role}"],
            )

        data = run_async(_get_data())
        return jsonify(data), 200

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
            result = await customer_svc.assign_customer(assistant_id, user_id)
            if result:
                cache_store = CacheStoreService(backboard)
                await cache_store.update_customer_summary(assistant_id)
            return result

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

    Reads from the cache assistant (single API call). No permission
    filter — managers see everything.

    Returns:
        JSON with users, customers, and aggregate stats
    """
    try:
        async def _get_data():
            backboard = BackboardService()
            cache_store = CacheStoreService(backboard)
            user_svc = UserService(backboard)
            cache = CacheService()

            cache_key = build_cache_key("manager_dashboard")

            async def _build():
                users = await user_svc.list_users()
                summaries = await cache_store.get_all_summaries()

                total_opportunities = 0
                total_activities = 0
                user_stats: dict[str, dict[str, int]] = {
                    u.id: {"customer_count": 0, "opportunity_count": 0, "activity_count": 0}
                    for u in users
                }

                customers = []
                for s in summaries:
                    total_opportunities += s.opportunity_count
                    total_activities += s.activity_count

                    customers.append({
                        "customer": {
                            "id": s.customer_id,
                            "company_name": s.company_name,
                            "domain": s.domain,
                            "industry": s.industry,
                            "size": s.size,
                            "assistant_id": s.assistant_id,
                            "assigned_user_id": s.assigned_user_id,
                            "created_at": s.created_at.isoformat() if s.created_at else None,
                            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                            "next_followup_date": s.next_followup_date.isoformat() if s.next_followup_date else None,
                        },
                        "opportunity_count": s.opportunity_count,
                        "activity_count": s.activity_count,
                    })

                    if s.assigned_user_id and s.assigned_user_id in user_stats:
                        user_stats[s.assigned_user_id]["customer_count"] += 1
                        user_stats[s.assigned_user_id]["opportunity_count"] += s.opportunity_count
                        user_stats[s.assigned_user_id]["activity_count"] += s.activity_count

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

            return await cache.get_or_set(
                cache_key,
                cache.with_jitter(CACHE_TTLS["manager_dashboard"]),
                _build,
                tags=["dashboards", "registry", "role:manager"],
            )

        data = run_async(_get_data())
        return jsonify(data), 200

    except Exception as e:
        current_app.logger.exception("Error getting manager dashboard data")
        return jsonify({"error": str(e)}), 500


@customers_bp.route("/global/contacts", methods=["GET"])
@login_required
def get_global_contacts():
    """Get all contacts across customers for async loading.

    Uses cache store summaries for permission filtering, then fetches
    per-customer contacts in parallel via asyncio.gather().

    Returns:
        JSON with contacts list
    """
    try:
        current_user = get_current_user()
        is_manager = current_user and current_user.is_manager()
        user_id = current_user.id if current_user else None

        async def _get_data():
            backboard = BackboardService()
            cache_store = CacheStoreService(backboard)
            customer_svc = CustomerService(backboard)
            cache = CacheService()

            role = "manager" if is_manager else "user"
            cache_key = build_cache_key("global_contacts", role, user_id or "none")

            async def _build():
                summaries = await cache_store.get_all_summaries()

                # Permission filter
                if not is_manager:
                    summaries = [s for s in summaries if s.assigned_user_id == user_id]

                # Parallel fetch all customer contacts
                async def _fetch_contacts(s):
                    result = []
                    for contact in await customer_svc.get_contacts(s.assistant_id):
                        contact_data = contact.model_dump(mode="json")
                        contact_data["assistant_id"] = s.assistant_id
                        contact_data["company_name"] = s.company_name
                        result.append(contact_data)
                    return result

                batches = await asyncio.gather(
                    *[_fetch_contacts(s) for s in summaries]
                )
                contacts = [c for batch in batches for c in batch]
                return {"contacts": contacts}

            return await cache.get_or_set(
                cache_key,
                cache.with_jitter(CACHE_TTLS["global_contacts"]),
                _build,
                tags=["global_lists", "registry", f"role:{role}", f"user:{user_id or 'none'}"],
            )

        data = run_async(_get_data())
        return jsonify(data), 200

    except Exception as e:
        current_app.logger.exception("Error getting global contacts")
        return jsonify({"error": str(e)}), 500


@customers_bp.route("/global/opportunities", methods=["GET"])
@login_required
def get_global_opportunities():
    """Get all opportunities across customers for async loading.

    Uses cache store summaries for permission filtering, then fetches
    per-customer opportunities in parallel via asyncio.gather().

    Returns:
        JSON with opportunities list
    """
    try:
        current_user = get_current_user()
        is_manager = current_user and current_user.is_manager()
        user_id = current_user.id if current_user else None

        async def _get_data():
            backboard = BackboardService()
            cache_store = CacheStoreService(backboard)
            customer_svc = CustomerService(backboard)
            cache = CacheService()

            role = "manager" if is_manager else "user"
            cache_key = build_cache_key("global_opportunities", role, user_id or "none")

            async def _build():
                summaries = await cache_store.get_all_summaries()

                if not is_manager:
                    summaries = [s for s in summaries if s.assigned_user_id == user_id]

                async def _fetch_opps(s):
                    result = []
                    for opp in await customer_svc.get_opportunities(s.assistant_id):
                        opp_data = opp.model_dump(mode="json")
                        opp_data["assistant_id"] = s.assistant_id
                        opp_data["company_name"] = s.company_name
                        result.append(opp_data)
                    return result

                batches = await asyncio.gather(
                    *[_fetch_opps(s) for s in summaries]
                )
                opportunities = [o for batch in batches for o in batch]
                return {"opportunities": opportunities}

            return await cache.get_or_set(
                cache_key,
                cache.with_jitter(CACHE_TTLS["global_opportunities"]),
                _build,
                tags=["global_lists", "registry", f"role:{role}", f"user:{user_id or 'none'}"],
            )

        data = run_async(_get_data())
        return jsonify(data), 200

    except Exception as e:
        current_app.logger.exception("Error getting global opportunities")
        return jsonify({"error": str(e)}), 500


@customers_bp.route("/global/activities", methods=["GET"])
@login_required
def get_global_activities():
    """Get all activities across customers for async loading.

    Uses cache store summaries for permission filtering, then fetches
    per-customer activities in parallel via asyncio.gather().

    Returns:
        JSON with activities list (sorted by date descending)
    """
    try:
        current_user = get_current_user()
        is_manager = current_user and current_user.is_manager()
        user_id = current_user.id if current_user else None

        async def _get_data():
            backboard = BackboardService()
            cache_store = CacheStoreService(backboard)
            customer_svc = CustomerService(backboard)
            cache = CacheService()

            role = "manager" if is_manager else "user"
            cache_key = build_cache_key("global_activities", role, user_id or "none")

            async def _build():
                summaries = await cache_store.get_all_summaries()

                if not is_manager:
                    summaries = [s for s in summaries if s.assigned_user_id == user_id]

                async def _fetch_activities(s):
                    result = []
                    for activity in await customer_svc.get_activities(s.assistant_id):
                        result.append({
                            "assistant_id": s.assistant_id,
                            "company_name": s.company_name,
                            "activity": activity,
                        })
                    return result

                batches = await asyncio.gather(
                    *[_fetch_activities(s) for s in summaries]
                )
                activity_rows = [r for batch in batches for r in batch]
                activity_rows.sort(key=lambda row: row["activity"].date, reverse=True)

                activities = []
                for row in activity_rows:
                    activity_data = row["activity"].model_dump(mode="json")
                    activity_data["assistant_id"] = row["assistant_id"]
                    activity_data["company_name"] = row["company_name"]
                    activities.append(activity_data)

                return {"activities": activities}

            return await cache.get_or_set(
                cache_key,
                cache.with_jitter(CACHE_TTLS["global_activities"]),
                _build,
                tags=["global_lists", "registry", f"role:{role}", f"user:{user_id or 'none'}"],
            )

        data = run_async(_get_data())
        return jsonify(data), 200

    except Exception as e:
        current_app.logger.exception("Error getting global activities")
        return jsonify({"error": str(e)}), 500
