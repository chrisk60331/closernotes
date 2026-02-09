"""Transcript ingestion API endpoints."""

import asyncio
import csv
import io
from datetime import date, datetime
from uuid import uuid4

from flask import Blueprint, request, jsonify, current_app

from app.schemas.ingest import IngestReport, IngestReportItem, MultiIngestRequest, ReportType
from app.schemas.meeting import IngestRequest, IngestResponse, TranscriptMetadata
from app.services.auth import login_required, get_current_user
from app.services.backboard import BackboardService
from app.services.orchestrator import OrchestratorService
from app.services.customer import CustomerService
from app.services.meeting import MeetingService
from app.services.crm import CRMService
from app.services.cache_store import CacheStoreService
from app.services.reports import ReportService

ingest_bp = Blueprint("ingest", __name__)


def run_async(coro):
    """Run an async coroutine in a sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _build_report(
    report_type: ReportType,
    items: list[IngestReportItem],
    source_label: str | None = None,
    followups: list[dict[str, str]] | None = None,
) -> IngestReport:
    """Build a report summary from item outcomes."""
    total_items = len(items)
    success_count = sum(1 for item in items if not item.error)
    error_count = total_items - success_count
    return IngestReport(
        report_id=str(uuid4()),
        report_type=report_type,
        total_items=total_items,
        success_count=success_count,
        error_count=error_count,
        items=items,
        source_label=source_label,
        followups=followups or [],
    )


def _coerce_csv_value(value: str | None) -> str | None:
    """Normalize CSV values for safe text rendering."""
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned if cleaned else None


def _normalize_header(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _extract_company_hint(row: dict[str, str], fieldnames: list[str]) -> str | None:
    """Find a likely company column from CSV data."""
    company_keys = {
        "company",
        "company_name",
        "customer",
        "customer_name",
        "account",
        "account_name",
    }
    for field in fieldnames:
        if _normalize_header(field) in company_keys:
            return _coerce_csv_value(row.get(field))

    # Fallback: use the first column value if it looks like a short name
    if fieldnames:
        first_val = _coerce_csv_value(row.get(fieldnames[0]))
        if first_val and len(first_val) < 100 and "@" not in first_val:
            return first_val

    return None


def _build_csv_row_transcript(row: dict[str, str], company_hint: str | None) -> str:
    """Convert a CSV row into a text blob for LLM processing."""
    lines = ["Opportunity import row."]
    if company_hint:
        lines.append(f"Company: {company_hint}")
    for key, value in row.items():
        if key is None:
            continue
        if not value:
            continue
        cleaned = _coerce_csv_value(value)
        if cleaned:
            lines.append(f"{key}: {cleaned}")
    return "\n".join(lines)


async def _process_transcript(
    data: IngestRequest,
    assigned_user_id: str | None,
    allow_unknown: bool = False,
) -> IngestResponse:
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

    from app.services.teammate import TeammateService
    from app.services.user import UserService

    teammate_svc = TeammateService(backboard)
    user_svc = UserService(backboard)

    # Ensure orchestrator exists
    await orchestrator.ensure_orchestrator_exists()

    # Load teammate names for LLM hints
    all_users = await user_svc.list_users()
    teammate_names = [u.name for u in all_users]

    # Route the transcript (with teammate awareness)
    routing = await orchestrator.route_transcript(
        transcript=data.transcript,
        metadata=data.metadata,
        teammate_names=teammate_names,
    )

    if routing["action"] == "need_clarification":
        if not allow_unknown:
            raise ValueError(routing.get("reason", "Could not determine customer"))
        routing["is_new_customer"] = True
        routing["customer_assistant_id"] = None
        routing["company_name"] = "Unknown Company"
        routing["company_domain"] = None
        routing["action"] = "create_customer"

    # Get or create customer
    is_new_customer = routing["is_new_customer"]
    company_name = routing["company_name"]

    if is_new_customer:
        # Create new customer — only add a dedup suffix for truly unknown names
        unknown_suffix = uuid4().hex[:6] if (allow_unknown and company_name == "Unknown Company") else None
        effective_name = (
            f"{company_name} {unknown_suffix}" if unknown_suffix else company_name
        )

        # Extract lead source from entity extraction (first-touch for customer)
        from app.schemas.enums import LeadSource as LeadSourceEnum
        entities = routing.get("entities", {})
        _raw_lead_source = entities.get("lead_source")
        _customer_lead_source = None
        if _raw_lead_source:
            try:
                _customer_lead_source = LeadSourceEnum(_raw_lead_source)
            except ValueError:
                _customer_lead_source = None
        _customer_lead_source_detail = entities.get("lead_source_detail")

        customer = await customer_svc.create_customer(
            company_name=effective_name,
            company_domain=routing.get("company_domain"),
            assigned_user_id=assigned_user_id,
            lead_source=_customer_lead_source,
            lead_source_detail=_customer_lead_source_detail,
        )
        customer_assistant_id = customer.assistant_id
        customer_id = customer.id

        if allow_unknown:
            # Register placeholder and real names so dashboards can see them.
            await orchestrator.register_customer(effective_name, customer_assistant_id)
        else:
            # Register with orchestrator
            await orchestrator.register_customer(company_name, customer_assistant_id)
    else:
        customer_assistant_id = routing["customer_assistant_id"]
        customer = await customer_svc.get_customer(customer_assistant_id)
        customer_id = customer.id if customer else ""
        if customer and assigned_user_id and customer.assigned_user_id is None:
            customer = await customer_svc.assign_customer(customer_assistant_id, assigned_user_id)


    # Create meeting thread
    thread_info = await meeting_svc.create_meeting_thread(
        customer_assistant_id=customer_assistant_id,
        meeting_type=data.metadata.call_type if data.metadata else "meeting",
        meeting_date=data.metadata.call_date if data.metadata else None,
        participants=data.metadata.contact_hints if data.metadata else None,
    )

    # Process transcript (with teammate awareness)
    notes, activity = await meeting_svc.process_transcript(
        thread_id=thread_info["thread_id"],
        customer_assistant_id=customer_assistant_id,
        customer_id=customer_id,
        company_name=company_name,
        transcript=data.transcript,
        metadata=data.metadata,
        teammate_names=teammate_names,
    )

    # Create/update CRM objects based on extracted data
    crm_updates = {
        "contacts_created": 0,
        "contacts_updated": 0,
        "contact_names_created": [],
        "contact_names_updated": [],
        "opportunity_names_created": [],
        "opportunity_updated": False,
        "followup_required": False,
        "followup_reason": None,
        "teammates_detected": 0,
        "teammates_skipped": [],
    }

    # Collect all contacts from entity extraction and meeting notes stakeholders
    from app.schemas.crm import ContactCreate
    
    # Get existing contacts to avoid duplicates
    existing_contacts = await crm_svc.list_contacts(customer_assistant_id)
    existing_by_name = {c.name.lower(): c for c in existing_contacts}
    seen_names = set(existing_by_name.keys())
    
    contacts_to_create = []
    # Track names flagged as teammates by the LLM
    llm_flagged_teammates: set[str] = set()
    
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
            crm_updates["contact_names_updated"].append(name)

    # From entity extraction
    entities = routing.get("entities", {})
    for contact_data in entities.get("contacts", []):
        if isinstance(contact_data, dict) and contact_data.get("name"):
            name = contact_data.get("name")
            # Track LLM teammate flags
            if contact_data.get("is_teammate"):
                llm_flagged_teammates.add(name.lower())
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
        # Track LLM teammate flags from stakeholders
        if stakeholder.is_teammate:
            llm_flagged_teammates.add(stakeholder.name.lower())
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

    # ---------------------------------------------------------------
    # Teammate detection: cross-reference all extracted names against
    # system users and filter them out of contact creation.
    # ---------------------------------------------------------------
    all_extracted_names = [c["name"] for c in contacts_to_create]
    # Also include LLM-flagged teammate names that may already be in seen_names
    all_extracted_names.extend(llm_flagged_teammates)

    detected_teammates = await teammate_svc.detect_teammates(
        extracted_names=all_extracted_names,
        current_user_id=assigned_user_id or "",
    )

    # Build a set of names to skip in contact creation
    teammate_name_set: set[str] = set()
    for tm in detected_teammates:
        teammate_name_set.add(tm.extracted_name.lower())
        teammate_name_set.add(tm.user_name.lower())

    # Also skip names the LLM flagged as teammates
    teammate_name_set.update(llm_flagged_teammates)

    crm_updates["teammates_detected"] = len(detected_teammates)
    crm_updates["teammates_skipped"] = [tm.user_name for tm in detected_teammates]

    # Filter contacts_to_create — remove teammates
    filtered_contacts = [
        c for c in contacts_to_create
        if c["name"].lower() not in teammate_name_set
    ]

    # Create all contacts (teammates excluded)
    for contact_data in filtered_contacts:
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
        crm_updates["contact_names_created"].append(contact_data["name"])

    # ---------------------------------------------------------------
    # Shared meeting linking: if teammates were detected, create/update
    # a SharedMeeting record and compare notes if another user already
    # ingested their version.
    # ---------------------------------------------------------------
    detected_teammates_dicts: list[dict] = []
    if detected_teammates:
        meeting_date = (
            data.metadata.call_date if data.metadata and data.metadata.call_date
            else datetime.utcnow()
        )
        shared = await teammate_svc.find_or_create_shared_meeting(
            customer_assistant_id=customer_assistant_id,
            customer_name=company_name,
            meeting_date=meeting_date,
            user_id=assigned_user_id or "",
            thread_id=thread_info["thread_id"],
            activity_id=activity.id,
            notes=notes,
        )

        # If another user already contributed notes, compare and flag
        if len(shared.user_notes) > 1:
            discrepancies = teammate_svc.compare_notes(shared)
            if discrepancies:
                await teammate_svc.create_discrepancy_items(
                    shared=shared,
                    discrepancies=discrepancies,
                    customer_assistant_id=customer_assistant_id,
                    customer_id=customer_id,
                )
                crm_updates["discrepancies_flagged"] = len(discrepancies)

        detected_teammates_dicts = [tm.model_dump() for tm in detected_teammates]

    # Auto-create opportunity if we have deal signals and none exists
    if is_new_customer and notes.deal_stage_signal:
        from app.schemas.crm import OpportunityCreate
        from app.schemas.enums import OpportunityStage, LeadSource as LeadSourceEnum2
        
        # Map deal stage signal to stage enum
        stage_map = {
            "discovery": OpportunityStage.DISCOVERY,
            "qualification": OpportunityStage.QUALIFICATION,
            "proposal": OpportunityStage.PROPOSAL,
            "negotiation": OpportunityStage.NEGOTIATION,
        }
        stage = stage_map.get(notes.deal_stage_signal.lower(), OpportunityStage.DISCOVERY)

        # Resolve lead source: prefer meeting notes, fall back to entity extraction
        _opp_lead_source = None
        _opp_lead_source_detail = None
        _raw_opp_ls = notes.lead_source or routing.get("entities", {}).get("lead_source")
        if _raw_opp_ls:
            try:
                _opp_lead_source = LeadSourceEnum2(_raw_opp_ls)
            except ValueError:
                _opp_lead_source = None
        _opp_lead_source_detail = notes.lead_source_detail or routing.get("entities", {}).get("lead_source_detail")
        
        opp_create = OpportunityCreate(
            customer_id=customer_id,
            name=f"{company_name} - Initial Opportunity",
            stage=stage,
            confidence=50 + notes.confidence_delta,
            competitors=notes.competitors_mentioned,
            lead_source=_opp_lead_source,
            lead_source_detail=_opp_lead_source_detail,
        )
        await crm_svc.create_opportunity(customer_assistant_id, opp_create)
        crm_updates["opportunity_created"] = True
        crm_updates["opportunity_names_created"].append(opp_create.name)

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

    if allow_unknown and "Unknown Company" in company_name:
        crm_updates["followup_required"] = True
        crm_updates["followup_reason"] = "Confirm customer company name."
        await customer_svc.set_customer_followup_date(
            customer_assistant_id,
            date.today(),
        )
        # Create a visible action item so users can resolve the name
        await crm_svc.create_promoted_action_item(
            assistant_id=customer_assistant_id,
            customer_id=customer_id,
            activity_id=thread_info["thread_id"],
            thread_id=thread_info["thread_id"],
            description="Resolve unknown company name — update the customer record with the correct company name.",
            owner="us",
            due_date=date.today(),
        )

    # Refresh denormalized cache
    cache_store = CacheStoreService(backboard)
    await cache_store.update_customer_summary(customer_assistant_id)

    return IngestResponse(
        meeting_id=thread_info["thread_id"],
        customer_id=customer_id,
        assistant_id=customer_assistant_id,
        customer_name=company_name if not allow_unknown else customer.company_name,
        is_new_customer=is_new_customer,
        notes=notes,
        crm_updates=crm_updates,
        detected_teammates=detected_teammates_dicts,
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
        current_user = get_current_user()
        assigned_user_id = current_user.id if current_user else None
        result = run_async(_process_transcript(data, assigned_user_id))

        return jsonify(result.model_dump(mode="json")), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.exception("Error processing transcript")
        return jsonify({"error": f"Internal error: {str(e)}"}), 500


@ingest_bp.route("/ingest/multi", methods=["POST"])
@login_required
def ingest_transcript_multi():
    """Ingest a brain dump that may contain multiple customers."""
    try:
        json_data = request.get_json()
        if not json_data:
            return jsonify({"error": "Request body is required"}), 400

        try:
            data = MultiIngestRequest.model_validate(json_data)
        except Exception as e:
            return jsonify({"error": f"Invalid request: {str(e)}"}), 400

        current_user = get_current_user()
        assigned_user_id = current_user.id if current_user else None

        async def _process_multi():
            backboard = BackboardService()
            orchestrator = OrchestratorService(backboard)
            report_svc = ReportService(backboard)

            from app.services.user import UserService
            user_svc = UserService(backboard)
            all_users = await user_svc.list_users()
            teammate_names = [u.name for u in all_users]
            teammate_names_lower = {n.lower() for n in teammate_names}

            segmentation = await orchestrator.segment_transcript_by_customer(
                transcript=data.transcript,
                metadata=data.metadata,
                teammate_names=teammate_names,
            )

            # Post-segmentation filter: drop segments whose company_name
            # matches a known teammate name (LLM sometimes creates a
            # segment for a teammate mention instead of a real customer).
            filtered_segments = []
            for seg in segmentation.segments:
                seg_name = (seg.company_name or "").strip().lower()
                if seg_name and seg_name in teammate_names_lower:
                    # Teammate name used as company — skip this segment
                    continue
                # Also check first-name matches for single-word company names
                if seg_name and " " not in seg_name:
                    first_names = {n.split()[0].lower() for n in teammate_names if n}
                    if seg_name in first_names:
                        continue
                filtered_segments.append(seg)

            # If all segments were filtered out, fall back to the
            # original transcript as a single segment
            if not filtered_segments:
                from app.schemas.ingest import MultiCustomerSegment
                filtered_segments = [
                    MultiCustomerSegment(
                        company_name=data.metadata.company_hint,
                        transcript=data.transcript,
                        contact_hints=data.metadata.contact_hints,
                        confidence=0.3,
                        rationale="All segments were teammate names; falling back to full transcript",
                    )
                ]

            items: list[IngestReportItem] = []
            followups: list[dict[str, str]] = []
            for index, segment in enumerate(filtered_segments):
                segment_source = {
                    "company_name": segment.company_name,
                    "company_domain": segment.company_domain,
                    "contact_hints": segment.contact_hints,
                    "confidence": segment.confidence,
                    "rationale": segment.rationale,
                }
                try:
                    segment_metadata = TranscriptMetadata(
                        caller_email=data.metadata.caller_email,
                        company_hint=segment.company_name or data.metadata.company_hint,
                        contact_hints=segment.contact_hints or data.metadata.contact_hints,
                        call_date=data.metadata.call_date,
                        call_type=data.metadata.call_type,
                        opportunity_id=data.metadata.opportunity_id,
                    )
                    ingest_request = IngestRequest(
                        transcript=segment.transcript,
                        metadata=segment_metadata,
                    )
                    result = await _process_transcript(
                        ingest_request,
                        assigned_user_id,
                        allow_unknown=True,
                    )
                    items.append(
                        IngestReportItem(
                            index=index,
                            company_name=result.customer_name,
                            customer_id=result.customer_id,
                            assistant_id=result.assistant_id,
                            meeting_id=result.meeting_id,
                            is_new_customer=result.is_new_customer,
                            summary=result.notes.summary if result.notes else None,
                            crm_updates=result.crm_updates,
                            source=segment_source,
                        )
                    )
                    if result.crm_updates.get("followup_required") and result.assistant_id:
                        followups.append(
                            {
                                "type": "missing_company_name",
                                "title": "Confirm customer company name",
                                "details": "Identify the correct customer for this transcript segment.",
                                "assistant_id": result.assistant_id,
                                "customer_name": result.customer_name,
                                "followup_date": date.today().isoformat(),
                            }
                        )
                except Exception as exc:
                    error_text = str(exc)
                    if "Could not determine customer company" in error_text:
                        followups.append(
                            {
                                "type": "missing_company_name",
                                "title": "Confirm customer company name",
                                "details": "Identify the correct customer for this transcript segment.",
                            }
                        )
                        items.append(
                            IngestReportItem(
                                index=index,
                                company_name="Unknown",
                                summary="Follow up to confirm customer name.",
                                crm_updates={
                                    "followup_required": True,
                                    "followup_reason": error_text,
                                },
                                source=segment_source,
                            )
                        )
                        continue
                    items.append(
                        IngestReportItem(
                            index=index,
                            company_name=segment.company_name,
                            source=segment_source,
                            error=str(exc),
                        )
                    )

            report = _build_report(
                ReportType.MULTI_TRANSCRIPT,
                items,
                source_label="Transcript",
                followups=followups,
            )
            await report_svc.store_report(report)
            return report

        report = run_async(_process_multi())
        return jsonify(report.model_dump(mode="json")), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.exception("Error processing multi-customer transcript")
        return jsonify({"error": f"Internal error: {str(e)}"}), 500


@ingest_bp.route("/ingest/opps/bulk", methods=["POST"])
@login_required
def ingest_opportunities_bulk():
    """Bulk ingest opportunities from a CSV file (legacy single-request)."""
    try:
        file = request.files.get("file")
        if not file:
            return jsonify({"error": "CSV file is required"}), 400

        try:
            raw_content = file.read().decode("utf-8", errors="ignore")
        except Exception:
            return jsonify({"error": "Unable to read CSV file"}), 400

        if not raw_content.strip():
            return jsonify({"error": "CSV file is empty"}), 400

        reader = csv.DictReader(io.StringIO(raw_content))
        fieldnames = reader.fieldnames or []
        rows = list(reader)
        if not rows:
            return jsonify({"error": "CSV file contains no rows"}), 400

        current_user = get_current_user()
        assigned_user_id = current_user.id if current_user else None

        async def _process_bulk():
            backboard = BackboardService()
            orchestrator = OrchestratorService(backboard)
            report_svc = ReportService(backboard)

            from app.services.user import UserService as _BulkUserSvc
            _bulk_user_svc = _BulkUserSvc(backboard)
            _bulk_users = await _bulk_user_svc.list_users()
            _bulk_teammate_names = [u.name for u in _bulk_users]

            items: list[IngestReportItem] = []
            followups: list[dict[str, str]] = []
            for row_index, row in enumerate(rows):
                company_hint = _extract_company_hint(row, fieldnames)
                row_text = _build_csv_row_transcript(row, company_hint)
                metadata = TranscriptMetadata(
                    company_hint=company_hint,
                    call_type="bulk_import",
                )
                segmentation = await orchestrator.segment_transcript_by_customer(
                    transcript=row_text,
                    metadata=metadata,
                    teammate_names=_bulk_teammate_names,
                )

                for segment in segmentation.segments:
                    segment_source = {
                        "row_number": row_index + 1,
                        "row": row,
                        "company_name": segment.company_name,
                        "company_domain": segment.company_domain,
                        "contact_hints": segment.contact_hints,
                        "confidence": segment.confidence,
                        "rationale": segment.rationale,
                    }
                    try:
                        segment_metadata = TranscriptMetadata(
                            company_hint=segment.company_name or company_hint,
                            contact_hints=segment.contact_hints,
                            call_type="bulk_import",
                        )
                        ingest_request = IngestRequest(
                            transcript=segment.transcript,
                            metadata=segment_metadata,
                        )
                        result = await _process_transcript(
                            ingest_request,
                            assigned_user_id,
                            allow_unknown=True,
                        )
                        items.append(
                            IngestReportItem(
                                index=len(items),
                                company_name=result.customer_name,
                                customer_id=result.customer_id,
                                assistant_id=result.assistant_id,
                                meeting_id=result.meeting_id,
                                is_new_customer=result.is_new_customer,
                                summary=result.notes.summary if result.notes else None,
                                crm_updates=result.crm_updates,
                                source=segment_source,
                            )
                        )
                        if result.crm_updates.get("followup_required") and result.assistant_id:
                            followups.append(
                                {
                                    "type": "missing_company_name",
                                    "title": "Confirm customer company name",
                                    "details": "Identify the correct customer for this CSV row.",
                                    "assistant_id": result.assistant_id,
                                    "customer_name": result.customer_name,
                                    "followup_date": date.today().isoformat(),
                                }
                            )
                    except Exception as exc:
                        error_text = str(exc)
                        if "Could not determine customer company" in error_text:
                            followups.append(
                                {
                                    "type": "missing_company_name",
                                    "title": "Confirm customer company name",
                                    "details": "Identify the correct customer for this CSV row.",
                                }
                            )
                            items.append(
                                IngestReportItem(
                                    index=len(items),
                                    company_name="Unknown",
                                    summary="Follow up to confirm customer name.",
                                    crm_updates={
                                        "followup_required": True,
                                        "followup_reason": error_text,
                                    },
                                    source=segment_source,
                                )
                            )
                            continue
                        items.append(
                            IngestReportItem(
                                index=len(items),
                                company_name=segment.company_name or company_hint,
                                source=segment_source,
                                error=str(exc),
                            )
                        )

            report = _build_report(
                ReportType.CSV_BULK,
                items,
                source_label=file.filename or "CSV Upload",
                followups=followups,
            )
            await report_svc.store_report(report)
            return report

        report = run_async(_process_bulk())
        return jsonify(report.model_dump(mode="json")), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.exception("Error processing bulk opportunity upload")
        return jsonify({"error": f"Internal error: {str(e)}"}), 500


@ingest_bp.route("/ingest/opps/bulk/row", methods=["POST"])
@login_required
def ingest_opportunity_row():
    """Process a single CSV row for bulk upload with progress tracking."""
    try:
        json_data = request.get_json()
        if not json_data:
            return jsonify({"error": "Request body is required"}), 400

        row = json_data.get("row", {})
        fieldnames = json_data.get("fieldnames", [])
        row_number = json_data.get("row_number", 0)

        if not row:
            return jsonify({"error": "Row data is required"}), 400

        current_user = get_current_user()
        assigned_user_id = current_user.id if current_user else None

        async def _process_single_row():
            backboard = BackboardService()
            orchestrator = OrchestratorService(backboard)

            from app.services.user import UserService as _RowUserSvc
            _row_user_svc = _RowUserSvc(backboard)
            _row_users = await _row_user_svc.list_users()
            _row_teammate_names = [u.name for u in _row_users]

            company_hint = _extract_company_hint(row, fieldnames)
            row_text = _build_csv_row_transcript(row, company_hint)
            metadata = TranscriptMetadata(
                company_hint=company_hint,
                call_type="bulk_import",
            )
            segmentation = await orchestrator.segment_transcript_by_customer(
                transcript=row_text,
                metadata=metadata,
                teammate_names=_row_teammate_names,
            )

            items: list[IngestReportItem] = []
            followups: list[dict[str, str]] = []

            for segment in segmentation.segments:
                segment_source = {
                    "row_number": row_number,
                    "row": row,
                    "company_name": segment.company_name,
                    "company_domain": segment.company_domain,
                    "contact_hints": segment.contact_hints,
                    "confidence": segment.confidence,
                    "rationale": segment.rationale,
                }
                try:
                    segment_metadata = TranscriptMetadata(
                        company_hint=segment.company_name or company_hint,
                        contact_hints=segment.contact_hints,
                        call_type="bulk_import",
                    )
                    ingest_request = IngestRequest(
                        transcript=segment.transcript,
                        metadata=segment_metadata,
                    )
                    result = await _process_transcript(
                        ingest_request,
                        assigned_user_id,
                        allow_unknown=True,
                    )
                    items.append(
                        IngestReportItem(
                            index=0,
                            company_name=result.customer_name,
                            customer_id=result.customer_id,
                            assistant_id=result.assistant_id,
                            meeting_id=result.meeting_id,
                            is_new_customer=result.is_new_customer,
                            summary=result.notes.summary if result.notes else None,
                            crm_updates=result.crm_updates,
                            source=segment_source,
                        )
                    )
                    if result.crm_updates.get("followup_required") and result.assistant_id:
                        followups.append(
                            {
                                "type": "missing_company_name",
                                "title": "Confirm customer company name",
                                "details": "Identify the correct customer for this CSV row.",
                                "assistant_id": result.assistant_id,
                                "customer_name": result.customer_name,
                                "followup_date": date.today().isoformat(),
                            }
                        )
                except Exception as exc:
                    error_text = str(exc)
                    if "Could not determine customer company" in error_text:
                        followups.append(
                            {
                                "type": "missing_company_name",
                                "title": "Confirm customer company name",
                                "details": "Identify the correct customer for this CSV row.",
                            }
                        )
                        items.append(
                            IngestReportItem(
                                index=0,
                                company_name="Unknown",
                                summary="Follow up to confirm customer name.",
                                crm_updates={
                                    "followup_required": True,
                                    "followup_reason": error_text,
                                },
                                source=segment_source,
                            )
                        )
                        continue
                    items.append(
                        IngestReportItem(
                            index=0,
                            company_name=segment.company_name or company_hint,
                            source=segment_source,
                            error=str(exc),
                        )
                    )

            return items, followups

        items, followups = run_async(_process_single_row())
        return jsonify({
            "items": [item.model_dump(mode="json") for item in items],
            "followups": followups,
        }), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.exception("Error processing bulk row")
        return jsonify({"error": f"Internal error: {str(e)}"}), 500


@ingest_bp.route("/ingest/opps/bulk/report", methods=["POST"])
@login_required
def create_bulk_report():
    """Create and store a report from accumulated bulk upload results."""
    try:
        json_data = request.get_json()
        if not json_data:
            return jsonify({"error": "Request body is required"}), 400

        items_data = json_data.get("items", [])
        followups = json_data.get("followups", [])
        source_label = json_data.get("source_label", "CSV Upload")

        items: list[IngestReportItem] = []
        for idx, item_data in enumerate(items_data):
            item_data["index"] = idx
            # Compact source to only what the report template needs
            source = item_data.get("source")
            if isinstance(source, dict):
                item_data["source"] = {
                    "row_number": source.get("row_number"),
                    "company_name": source.get("company_name"),
                }
            items.append(IngestReportItem.model_validate(item_data))

        async def _create_report():
            backboard = BackboardService()
            report_svc = ReportService(backboard)
            report = _build_report(
                ReportType.CSV_BULK,
                items,
                source_label=source_label,
                followups=followups,
            )
            await report_svc.store_report(report)
            return report

        report = run_async(_create_report())
        return jsonify({"report_id": report.report_id}), 200

    except Exception as e:
        current_app.logger.exception("Error creating bulk report")
        return jsonify({"error": f"Internal error: {str(e)}"}), 500
