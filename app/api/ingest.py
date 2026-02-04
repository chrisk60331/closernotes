"""Transcript ingestion API endpoints."""

import asyncio
from flask import Blueprint, request, jsonify, current_app

from app.schemas.meeting import IngestRequest, IngestResponse, TranscriptMetadata
from app.services.auth import login_required
from app.services.backboard import BackboardService
from app.services.orchestrator import OrchestratorService
from app.services.customer import CustomerService
from app.services.meeting import MeetingService
from app.services.crm import CRMService

ingest_bp = Blueprint("ingest", __name__)


def run_async(coro):
    """Run an async coroutine in a sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _process_transcript(data: IngestRequest) -> IngestResponse:
    """Process a transcript through the full pipeline.

    Args:
        data: Ingestion request with transcript and metadata

    Returns:
        Ingestion response with results
    """
    backboard = BackboardService()
    orchestrator = OrchestratorService(backboard)
    customer_svc = CustomerService(backboard)
    meeting_svc = MeetingService(backboard)
    crm_svc = CRMService(backboard)

    # Ensure orchestrator exists
    await orchestrator.ensure_orchestrator_exists()

    # Route the transcript
    routing = await orchestrator.route_transcript(
        transcript=data.transcript,
        metadata=data.metadata,
    )

    if routing["action"] == "need_clarification":
        raise ValueError(routing.get("reason", "Could not determine customer"))

    # Get or create customer
    is_new_customer = routing["is_new_customer"]
    company_name = routing["company_name"]

    if is_new_customer:
        # Create new customer
        customer = await customer_svc.create_customer(
            company_name=company_name,
            company_domain=routing.get("company_domain"),
        )
        customer_assistant_id = customer.assistant_id
        customer_id = customer.id

        # Register with orchestrator
        await orchestrator.register_customer(company_name, customer_assistant_id)
    else:
        customer_assistant_id = routing["customer_assistant_id"]
        customer = await customer_svc.get_customer(customer_assistant_id)
        customer_id = customer.id if customer else ""

    # Create meeting thread
    thread_info = await meeting_svc.create_meeting_thread(
        customer_assistant_id=customer_assistant_id,
        meeting_type=data.metadata.call_type if data.metadata else "meeting",
        meeting_date=data.metadata.call_date if data.metadata else None,
        participants=data.metadata.contact_hints if data.metadata else None,
    )

    # Process transcript
    notes, activity = await meeting_svc.process_transcript(
        thread_id=thread_info["thread_id"],
        customer_assistant_id=customer_assistant_id,
        customer_id=customer_id,
        company_name=company_name,
        transcript=data.transcript,
        metadata=data.metadata,
    )

    # Create/update CRM objects based on extracted data
    crm_updates = {"contacts_created": 0, "contacts_updated": 0}

    # Collect all contacts from entity extraction and meeting notes stakeholders
    from app.schemas.crm import ContactCreate
    
    # Get existing contacts to avoid duplicates
    existing_contacts = await crm_svc.list_contacts(customer_assistant_id)
    existing_by_name = {c.name.lower(): c for c in existing_contacts}
    seen_names = set(existing_by_name.keys())
    
    contacts_to_create = []
    
    def normalize_contact_method(raw_method: str | None):
        from app.schemas.enums import ContactMethod

        if not raw_method:
            return None
        if isinstance(raw_method, ContactMethod):
            return raw_method
        if not isinstance(raw_method, str):
            return None

        method_map = {
            "email": ContactMethod.EMAIL,
            "text": ContactMethod.TEXT,
            "sms": ContactMethod.TEXT,
            "call": ContactMethod.CALL,
            "phone": ContactMethod.CALL,
            "whatsapp": ContactMethod.WHATSAPP,
        }
        return method_map.get(raw_method.strip().lower())

    async def update_existing_contact(name: str, contact_data: dict) -> None:
        existing = existing_by_name.get(name.lower())
        if not existing:
            return

        updates = {}
        if contact_data.get("email") and not existing.email:
            updates["email"] = contact_data.get("email")
        pref_method = normalize_contact_method(contact_data.get("preferred_contact_method"))
        if pref_method and not existing.preferred_contact_method:
            updates["preferred_contact_method"] = pref_method

        if updates:
            await crm_svc.update_contact(
                customer_assistant_id,
                existing.id,
                **updates,
            )
            crm_updates["contacts_updated"] += 1

    # From entity extraction
    entities = routing.get("entities", {})
    for contact_data in entities.get("contacts", []):
        if isinstance(contact_data, dict) and contact_data.get("name"):
            name = contact_data.get("name")
            if name.lower() in seen_names:
                await update_existing_contact(name, contact_data)
            else:
                seen_names.add(name.lower())
                contacts_to_create.append({
                    "name": name,
                    "email": contact_data.get("email"),
                    "role": contact_data.get("role"),
                    "is_champion": contact_data.get("is_likely_champion", False),
                    "is_decision_maker": contact_data.get("is_likely_decision_maker", False),
                    "preferred_contact_method": contact_data.get("preferred_contact_method"),
                })
    
    # From meeting notes stakeholders
    for stakeholder in notes.stakeholders:
        if not stakeholder.name:
            continue
        if stakeholder.name.lower() in seen_names:
            await update_existing_contact(
                stakeholder.name,
                {
                    "email": stakeholder.email,
                    "preferred_contact_method": stakeholder.preferred_contact_method.value
                    if stakeholder.preferred_contact_method
                    else None,
                },
            )
        else:
            seen_names.add(stakeholder.name.lower())
            contacts_to_create.append({
                "name": stakeholder.name,
                "email": stakeholder.email,
                "role": stakeholder.role,
                "is_champion": stakeholder.sentiment == "positive",
                "is_decision_maker": "decision" in (stakeholder.role or "").lower() or "cto" in (stakeholder.role or "").lower() or "ceo" in (stakeholder.role or "").lower(),
                "preferred_contact_method": stakeholder.preferred_contact_method.value if stakeholder.preferred_contact_method else None,
            })
    
    # Create all contacts
    for contact_data in contacts_to_create:
        # Convert preferred_contact_method string to enum if present
        pref_method = None
        pref_method_str = contact_data.get("preferred_contact_method")
        if pref_method_str:
            pref_method = normalize_contact_method(pref_method_str)
        
        contact_create = ContactCreate(
            customer_id=customer_id,
            name=contact_data["name"],
            email=contact_data.get("email"),
            role=contact_data.get("role"),
            is_champion=contact_data.get("is_champion", False),
            is_decision_maker=contact_data.get("is_decision_maker", False),
            preferred_contact_method=pref_method,
        )
        await crm_svc.create_contact(customer_assistant_id, contact_create)
        crm_updates["contacts_created"] += 1

    # Auto-create opportunity if we have deal signals and none exists
    if is_new_customer and notes.deal_stage_signal:
        from app.schemas.crm import OpportunityCreate
        from app.schemas.enums import OpportunityStage
        
        # Map deal stage signal to stage enum
        stage_map = {
            "discovery": OpportunityStage.DISCOVERY,
            "qualification": OpportunityStage.QUALIFICATION,
            "proposal": OpportunityStage.PROPOSAL,
            "negotiation": OpportunityStage.NEGOTIATION,
        }
        stage = stage_map.get(notes.deal_stage_signal.lower(), OpportunityStage.DISCOVERY)
        
        opp_create = OpportunityCreate(
            customer_id=customer_id,
            name=f"{company_name} - Initial Opportunity",
            stage=stage,
            confidence=50 + notes.confidence_delta,
            competitors=notes.competitors_mentioned,
        )
        await crm_svc.create_opportunity(customer_assistant_id, opp_create)
        crm_updates["opportunity_created"] = True

    # Update opportunity if linked
    if data.metadata and data.metadata.opportunity_id:
        updated_opp = await crm_svc.update_opportunity_from_meeting(
            assistant_id=customer_assistant_id,
            opportunity_id=data.metadata.opportunity_id,
            stage_signal=notes.deal_stage_signal,
            confidence_delta=notes.confidence_delta,
            competitors=notes.competitors_mentioned,
        )
        if updated_opp:
            crm_updates["opportunity_updated"] = True

    return IngestResponse(
        meeting_id=thread_info["thread_id"],
        customer_id=customer_id,
        assistant_id=customer_assistant_id,
        customer_name=company_name,
        is_new_customer=is_new_customer,
        notes=notes,
        crm_updates=crm_updates,
    )


@ingest_bp.route("/ingest", methods=["POST"])
@login_required
def ingest_transcript():
    """Ingest a meeting transcript.

    Request body:
        {
            "transcript": "Meeting transcript text...",
            "metadata": {
                "caller_email": "user@example.com",
                "company_hint": "Acme Corp",
                "contact_hints": ["John Smith"],
                "call_date": "2024-01-15T10:00:00Z",
                "call_type": "meeting",
                "opportunity_id": "optional-opp-id"
            }
        }

    Returns:
        JSON response with meeting ID, notes, and CRM updates
    """
    try:
        json_data = request.get_json()
        if not json_data:
            return jsonify({"error": "Request body is required"}), 400

        # Parse and validate request
        try:
            data = IngestRequest.model_validate(json_data)
        except Exception as e:
            return jsonify({"error": f"Invalid request: {str(e)}"}), 400

        # Process the transcript
        result = run_async(_process_transcript(data))

        return jsonify(result.model_dump(mode="json")), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.exception("Error processing transcript")
        return jsonify({"error": f"Internal error: {str(e)}"}), 500
