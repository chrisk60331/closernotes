"""UI routes for the CloserNotes web interface."""

import asyncio
import re
from markupsafe import escape
from flask import Blueprint, render_template, current_app, request, redirect, url_for, flash

from app.services.auth import login_required, manager_required, get_current_user
from app.services.backboard import BackboardService
from app.services.orchestrator import OrchestratorService
from app.services.customer import CustomerService
from app.services.meeting import MeetingService
from app.services.crm import CRMService

ui_bp = Blueprint("ui", __name__)


def run_async(coro):
    """Run an async coroutine in a sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@ui_bp.route("/")
@login_required
def dashboard():
    """Render the main dashboard.
    
    Renders immediately with loading state, data is fetched via AJAX.
    """
    return render_template(
        "dashboard.html",
        customers=None,  # None indicates loading state
        customer_count=0,
        todays_followups=None,
    )


@ui_bp.route("/manager")
@manager_required
def manager_dashboard():
    """Render the manager dashboard.
    
    Renders immediately with loading state, data is fetched via AJAX.
    """
    return render_template("manager.html")


@ui_bp.route("/customer/<assistant_id>")
@login_required
def customer_detail(assistant_id: str):
    """Render customer detail page."""
    try:
        async def _get_data():
            backboard = BackboardService()
            customer_svc = CustomerService(backboard)
            meeting_svc = MeetingService(backboard)

            summary = await customer_svc.get_customer_summary(assistant_id)
            meetings = await meeting_svc.get_customer_meetings(assistant_id, limit=50)

            # Get next follow-up date (calculated if not set)
            next_followup_date = await customer_svc.get_customer_next_followup(assistant_id)

            # Aggregate products and sales value across all meetings
            all_products = set()
            total_sales_value = 0.0
            for meeting in meetings:
                for product in meeting.get("products_discussed", []) or []:
                    all_products.add(product)
                if meeting.get("sales_value"):
                    total_sales_value += meeting["sales_value"]

            return {
                **summary,
                "meetings": meetings[:10],  # Only show 10 in the UI
                "all_products": sorted(all_products),
                "total_sales_value": total_sales_value if total_sales_value > 0 else None,
                "next_followup_date": next_followup_date.isoformat() if next_followup_date else None,
            }

        data = run_async(_get_data())

        if not data.get("customer"):
            flash("Customer not found", "error")
            return redirect(url_for("ui.dashboard"))

        return render_template("customer.html", **data)

    except Exception as e:
        current_app.logger.exception("Error loading customer")
        flash(f"Error loading customer: {str(e)}", "error")
        return redirect(url_for("ui.dashboard"))


def _linkify_names_in_text(
    text: str,
    assistant_id: str,
    customer_name: str | None,
    contacts: list,
) -> str:
    """Replace customer and contact names in text with clickable pill links.
    
    Args:
        text: The text to process
        assistant_id: The customer assistant ID for building URLs
        customer_name: Company name to match
        contacts: List of contact dicts with id and name
        
    Returns:
        HTML string with names replaced by clickable pills
    """
    if not text:
        return text
    
    # Escape the text first to prevent XSS
    result = str(escape(text))
    
    # Build replacement map: name -> (url, is_customer)
    replacements = []
    
    # Add customer name (company)
    if customer_name:
        replacements.append({
            "name": customer_name,
            "url": f"/customer/{assistant_id}",
            "is_customer": True,
        })
    
    # Add contact names
    for contact in contacts:
        if contact.get("name"):
            replacements.append({
                "name": contact["name"],
                "url": f"/customer/{assistant_id}/contact/{contact['id']}",
                "is_customer": False,
            })
    
    # Sort by name length (longest first) to avoid partial replacements
    replacements.sort(key=lambda x: len(x["name"]), reverse=True)
    
    # Replace each name with a pill
    for repl in replacements:
        name = repl["name"]
        url = repl["url"]
        
        # Customer pill (blue)
        if repl["is_customer"]:
            pill_html = (
                f'<a href="{url}" class="inline-flex items-center px-2 py-0.5 mx-0.5 '
                f'rounded-full text-xs font-medium bg-bb-blue/10 text-bb-blue '
                f'dark:bg-bb-blue/20 hover:bg-bb-blue/20 dark:hover:bg-bb-blue/30 '
                f'transition-colors no-underline">{escape(name)}</a>'
            )
        # Contact pill (gray)
        else:
            pill_html = (
                f'<a href="{url}" class="inline-flex items-center px-2 py-0.5 mx-0.5 '
                f'rounded-full text-xs font-medium bg-gray-100 text-gray-700 '
                f'dark:bg-gray-700 dark:text-gray-300 hover:bg-gray-200 '
                f'dark:hover:bg-gray-600 transition-colors no-underline">{escape(name)}</a>'
            )
        
        # Case-insensitive replacement, preserving word boundaries
        pattern = re.compile(re.escape(str(escape(name))), re.IGNORECASE)
        result = pattern.sub(pill_html, result)
    
    return result


def _render_meeting_detail(thread_id: str, assistant_id: str | None = None):
    """Render meeting detail page with optional summary context."""
    try:
        async def _get_data():
            backboard = BackboardService()
            meeting_svc = MeetingService(backboard)
            customer_svc = CustomerService(backboard)

            meeting = await meeting_svc.get_meeting(thread_id)
            summary = None
            customer = None
            contacts = []
            
            if assistant_id:
                meetings = await meeting_svc.get_customer_meetings(assistant_id, limit=50)
                summary = next(
                    (item for item in meetings if item.get("thread_id") == thread_id),
                    None,
                )
                # Fetch customer and contacts for clickable pills
                customer = await customer_svc.get_customer(assistant_id)
                contacts = await customer_svc.get_contacts(assistant_id)

            return meeting, summary, customer, contacts

        meeting, summary, customer, contacts = run_async(_get_data())

        if not meeting:
            return render_template("meeting.html", error="Meeting not found"), 404

        # Process summary text to linkify customer/contact names
        summary_html = None
        if summary and summary.get("summary") and customer:
            contacts_data = [c.model_dump(mode="json") for c in contacts]
            summary_html = _linkify_names_in_text(
                text=summary["summary"],
                assistant_id=assistant_id,
                customer_name=customer.company_name,
                contacts=contacts_data,
            )

        return render_template(
            "meeting.html",
            meeting=meeting,
            meeting_summary=summary,
            summary_html=summary_html,
            assistant_id=assistant_id,
            customer=customer.model_dump(mode="json") if customer else None,
            contacts=[c.model_dump(mode="json") for c in contacts],
        )

    except Exception as e:
        current_app.logger.exception("Error loading meeting")
        return render_template("meeting.html", error=str(e)), 500


@ui_bp.route("/meeting/<thread_id>")
@login_required
def meeting_detail(thread_id: str):
    """Render meeting detail page (thread-only route)."""
    return _render_meeting_detail(thread_id)


@ui_bp.route("/meeting/<assistant_id>/<thread_id>")
@login_required
def meeting_detail_with_customer(assistant_id: str, thread_id: str):
    """Render meeting detail page with customer context."""
    return _render_meeting_detail(thread_id, assistant_id=assistant_id)


# ============================================================================
# Contacts Routes
# ============================================================================

@ui_bp.route("/customer/<assistant_id>/contacts")
@login_required
def contacts_list(assistant_id: str):
    """Render contacts list for a customer."""
    try:
        async def _get_data():
            backboard = BackboardService()
            customer_svc = CustomerService(backboard)

            customer = await customer_svc.get_customer(assistant_id)
            contacts = await customer_svc.get_contacts(assistant_id)

            return {
                "customer": customer.model_dump(mode="json") if customer else None,
                "contacts": [c.model_dump(mode="json") for c in contacts],
                "assistant_id": assistant_id,
            }

        data = run_async(_get_data())

        if not data.get("customer"):
            return render_template("contacts.html", error="Customer not found"), 404

        return render_template("contacts.html", **data)

    except Exception as e:
        current_app.logger.exception("Error loading contacts")
        return render_template("contacts.html", error=str(e)), 500


@ui_bp.route("/customer/<assistant_id>/contact/<contact_id>")
@login_required
def contact_detail(assistant_id: str, contact_id: str):
    """Render contact detail page."""
    try:
        async def _get_data():
            backboard = BackboardService()
            customer_svc = CustomerService(backboard)
            crm_svc = CRMService(backboard)

            customer = await customer_svc.get_customer(assistant_id)
            contact = await crm_svc.get_contact(assistant_id, contact_id)

            return {
                "customer": customer.model_dump(mode="json") if customer else None,
                "contact": contact.model_dump(mode="json") if contact else None,
                "assistant_id": assistant_id,
            }

        data = run_async(_get_data())

        if not data.get("customer"):
            return render_template("contact_detail.html", error="Customer not found"), 404
        if not data.get("contact"):
            return render_template("contact_detail.html", error="Contact not found"), 404

        return render_template("contact_detail.html", **data)

    except Exception as e:
        current_app.logger.exception("Error loading contact")
        return render_template("contact_detail.html", error=str(e)), 500


# ============================================================================
# Opportunities Routes
# ============================================================================

@ui_bp.route("/customer/<assistant_id>/opportunities")
@login_required
def opportunities_list(assistant_id: str):
    """Render opportunities list for a customer."""
    try:
        async def _get_data():
            backboard = BackboardService()
            customer_svc = CustomerService(backboard)

            customer = await customer_svc.get_customer(assistant_id)
            opportunities = await customer_svc.get_opportunities(assistant_id)

            return {
                "customer": customer.model_dump(mode="json") if customer else None,
                "opportunities": [o.model_dump(mode="json") for o in opportunities],
                "assistant_id": assistant_id,
            }

        data = run_async(_get_data())

        if not data.get("customer"):
            return render_template("opportunities.html", error="Customer not found"), 404

        return render_template("opportunities.html", **data)

    except Exception as e:
        current_app.logger.exception("Error loading opportunities")
        return render_template("opportunities.html", error=str(e)), 500


@ui_bp.route("/customer/<assistant_id>/opportunity/<opportunity_id>")
@login_required
def opportunity_detail(assistant_id: str, opportunity_id: str):
    """Render opportunity detail page."""
    try:
        async def _get_data():
            backboard = BackboardService()
            customer_svc = CustomerService(backboard)
            crm_svc = CRMService(backboard)

            customer = await customer_svc.get_customer(assistant_id)
            opportunity = await crm_svc.get_opportunity(assistant_id, opportunity_id)

            return {
                "customer": customer.model_dump(mode="json") if customer else None,
                "opportunity": opportunity.model_dump(mode="json") if opportunity else None,
                "assistant_id": assistant_id,
            }

        data = run_async(_get_data())

        if not data.get("customer"):
            return render_template("opportunity_detail.html", error="Customer not found"), 404
        if not data.get("opportunity"):
            return render_template("opportunity_detail.html", error="Opportunity not found"), 404

        return render_template("opportunity_detail.html", **data)

    except Exception as e:
        current_app.logger.exception("Error loading opportunity")
        return render_template("opportunity_detail.html", error=str(e)), 500


# ============================================================================
# Activities Routes
# ============================================================================

@ui_bp.route("/customer/<assistant_id>/activities")
@login_required
def activities_list(assistant_id: str):
    """Render activities list for a customer."""
    try:
        async def _get_data():
            backboard = BackboardService()
            customer_svc = CustomerService(backboard)

            customer = await customer_svc.get_customer(assistant_id)
            activities = await customer_svc.get_activities(assistant_id)

            return {
                "customer": customer.model_dump(mode="json") if customer else None,
                "activities": [a.model_dump(mode="json") for a in activities],
                "assistant_id": assistant_id,
            }

        data = run_async(_get_data())

        if not data.get("customer"):
            return render_template("activities.html", error="Customer not found"), 404

        return render_template("activities.html", **data)

    except Exception as e:
        current_app.logger.exception("Error loading activities")
        return render_template("activities.html", error=str(e)), 500


@ui_bp.route("/customer/<assistant_id>/activity/<activity_id>")
@login_required
def activity_detail(assistant_id: str, activity_id: str):
    """Render activity detail page."""
    try:
        async def _get_data():
            backboard = BackboardService()
            customer_svc = CustomerService(backboard)
            crm_svc = CRMService(backboard)

            customer = await customer_svc.get_customer(assistant_id)
            activity = await crm_svc.get_activity(assistant_id, activity_id)

            return {
                "customer": customer.model_dump(mode="json") if customer else None,
                "activity": activity.model_dump(mode="json") if activity else None,
                "assistant_id": assistant_id,
            }

        data = run_async(_get_data())

        if not data.get("customer"):
            return render_template("activity_detail.html", error="Customer not found"), 404
        if not data.get("activity"):
            return render_template("activity_detail.html", error="Activity not found"), 404

        return render_template("activity_detail.html", **data)

    except Exception as e:
        current_app.logger.exception("Error loading activity")
        return render_template("activity_detail.html", error=str(e)), 500


# ============================================================================
# Action Items Routes
# ============================================================================

@ui_bp.route("/customer/<assistant_id>/action-items")
@login_required
def action_items_list(assistant_id: str):
    """Render action items list for a customer."""
    try:
        # Get filter from query params
        filter_status = request.args.get("filter", "all")

        async def _get_data():
            backboard = BackboardService()
            customer_svc = CustomerService(backboard)
            crm_svc = CRMService(backboard)

            customer = await customer_svc.get_customer(assistant_id)

            # Adjust filters based on query param
            include_completed = filter_status in ["all", "completed"]
            include_dismissed = False

            if filter_status == "completed":
                # Only get completed items
                all_items = await crm_svc.list_promoted_action_items(
                    assistant_id, include_dismissed=False, include_completed=True
                )
                items = [i for i in all_items if i.is_completed]
            elif filter_status == "pending":
                # Only pending items
                items = await crm_svc.list_promoted_action_items(
                    assistant_id, include_dismissed=False, include_completed=False
                )
            else:
                # All items
                items = await crm_svc.list_promoted_action_items(
                    assistant_id, include_dismissed=False, include_completed=True
                )

            return {
                "customer": customer.model_dump(mode="json") if customer else None,
                "action_items": [i.model_dump(mode="json") for i in items],
                "assistant_id": assistant_id,
                "filter_status": filter_status,
            }

        data = run_async(_get_data())

        if not data.get("customer"):
            return render_template("action_items.html", error="Customer not found"), 404

        return render_template("action_items.html", **data)

    except Exception as e:
        current_app.logger.exception("Error loading action items")
        return render_template("action_items.html", error=str(e)), 500


@ui_bp.route("/customer/<assistant_id>/action-item/<action_item_id>")
@login_required
def action_item_detail(assistant_id: str, action_item_id: str):
    """Render action item detail/lineage page."""
    try:
        async def _get_data():
            backboard = BackboardService()
            customer_svc = CustomerService(backboard)
            crm_svc = CRMService(backboard)

            customer = await customer_svc.get_customer(assistant_id)
            action_item = await crm_svc.get_promoted_action_item(assistant_id, action_item_id)

            # Get the source activity for context
            activity = None
            if action_item:
                activity = await crm_svc.get_activity(assistant_id, action_item.activity_id)

            return {
                "customer": customer.model_dump(mode="json") if customer else None,
                "action_item": action_item.model_dump(mode="json") if action_item else None,
                "activity": activity.model_dump(mode="json") if activity else None,
                "assistant_id": assistant_id,
            }

        data = run_async(_get_data())

        if not data.get("customer"):
            return render_template("action_item_detail.html", error="Customer not found"), 404
        if not data.get("action_item"):
            return render_template("action_item_detail.html", error="Action item not found"), 404

        return render_template("action_item_detail.html", **data)

    except Exception as e:
        current_app.logger.exception("Error loading action item")
        return render_template("action_item_detail.html", error=str(e)), 500
