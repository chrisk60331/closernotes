"""Orchestrator service for managing the CloserNotes orchestrator assistant."""

import json
import re
from datetime import datetime
from typing import Any

from app.config import get_settings
from app.prompts.orchestrator import get_multi_customer_segment_prompt
from app.prompts.extraction import (
    get_company_name_prompt,
    get_entity_extraction_prompt,
)
from app.schemas.ingest import MultiCustomerSegmentation, MultiCustomerSegment
from app.schemas.meeting import EntityExtraction, TranscriptMetadata, StakeholderMention
from app.services.backboard import BackboardService, get_backboard_service
from app.services.cache import CacheService, CACHE_TTLS, build_cache_key


class OrchestratorService:
    """Service for managing the CloserNotes orchestrator assistant."""

    def __init__(self, backboard: BackboardService):
        """Initialize the orchestrator service.

        Args:
            backboard: BackboardService instance
        """
        self._backboard = backboard
        self._settings = get_settings()
        self._assistant_id: str = self._settings.orchestrator_assistant_id
        self._customer_registry: dict[str, str] = {}  # company_name -> assistant_id
        self._cache = CacheService()
        self._registry_loaded = False

    @property
    def assistant_id(self) -> str:
        """Get the orchestrator assistant ID."""
        return self._assistant_id

    async def ensure_orchestrator_exists(self) -> str:
        """Load the customer registry from the orchestrator assistant.

        Returns:
            The orchestrator assistant ID
        """
        if self._registry_loaded:
            return self._assistant_id

        await self._load_customer_registry()
        self._registry_loaded = True
        return self._assistant_id

    async def _load_customer_registry(self) -> None:
        """Load the customer registry from orchestrator memory.

        Reads individual ``customer_registration`` memories (one per customer).
        For backward-compatibility, also reads any legacy monolithic
        ``customer_registry`` blob and migrates its entries to sharded
        memories so the old blob can be deleted.
        """
        if not self._assistant_id:
            return

        legacy_memory_id: str | None = None
        legacy_customers: list[dict[str, str]] = []

        try:
            memories = await self._backboard.get_memories(self._assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    mem_type = data.get("type")

                    if mem_type == "customer_registration":
                        # New sharded format: one memory per customer
                        name = data.get("company_name", "")
                        aid = data.get("assistant_id", "")
                        if name and aid:
                            normalized = self._normalize_company_name(name)
                            self._customer_registry[normalized] = aid

                    elif mem_type == "customer_registry":
                        # Legacy monolithic blob — collect for migration
                        legacy_memory_id = (
                            getattr(memory, "memory_id", None)
                            or getattr(memory, "id", None)
                        )
                        if legacy_memory_id is not None:
                            legacy_memory_id = str(legacy_memory_id)
                        for customer in data.get("customers", []):
                            legacy_customers.append(customer)

                except (json.JSONDecodeError, KeyError):
                    continue
        except Exception:
            self._customer_registry = {}
            return

        # Migrate legacy entries to sharded memories
        if legacy_customers:
            for customer in legacy_customers:
                name = customer.get("company_name", "")
                aid = customer.get("assistant_id", "")
                if not name or not aid:
                    continue
                normalized = self._normalize_company_name(name)
                if normalized not in self._customer_registry:
                    self._customer_registry[normalized] = aid
                    # Persist as individual memory
                    await self._save_single_registration(normalized, aid)

            # Delete the old monolithic blob
            if legacy_memory_id:
                try:
                    await self._backboard.delete_memory(
                        self._assistant_id, legacy_memory_id,
                    )
                except Exception:
                    pass  # Non-fatal; will be cleaned up next load

    async def _save_single_registration(
        self, normalized_name: str, assistant_id: str,
    ) -> None:
        """Persist a single customer registration as its own memory."""
        if not self._assistant_id:
            return

        entry = {
            "type": "customer_registration",
            "company_name": normalized_name,
            "assistant_id": assistant_id,
            "registered_at": datetime.utcnow().isoformat(),
        }
        await self._backboard.add_memory(
            assistant_id=self._assistant_id,
            content=json.dumps(entry),
        )

    def _normalize_company_name(self, name: str | None) -> str:
        """Normalize a company name for matching.

        Removes common suffixes and normalizes whitespace/case.

        Args:
            name: Raw company name

        Returns:
            Normalized company name for comparison
        """
        if not name:
            return ""
        
        # Lowercase and strip
        normalized = name.lower().strip()

        # Remove common suffixes
        suffixes = [
            r"\s+inc\.?$",
            r"\s+corp\.?$",
            r"\s+corporation$",
            r"\s+llc\.?$",
            r"\s+ltd\.?$",
            r"\s+limited$",
            r"\s+co\.?$",
            r"\s+company$",
            r",\s*inc\.?$",
        ]
        for suffix in suffixes:
            normalized = re.sub(suffix, "", normalized, flags=re.IGNORECASE)

        # Normalize whitespace
        normalized = re.sub(r"\s+", " ", normalized).strip()

        return normalized

    def _extract_domain_from_email(self, email: str) -> str | None:
        """Extract company domain from an email address."""
        if not email or "@" not in email:
            return None
        domain = email.split("@")[1].lower()
        # Ignore common email providers
        common_providers = [
            "gmail.com",
            "yahoo.com",
            "hotmail.com",
            "outlook.com",
            "icloud.com",
        ]
        if domain in common_providers:
            return None
        return domain

    async def extract_entities(
        self,
        transcript: str,
        metadata: TranscriptMetadata | None = None,
        teammate_names: list[str] | None = None,
    ) -> EntityExtraction:
        """Extract entities from a transcript for routing.

        Args:
            transcript: The meeting transcript text
            metadata: Optional metadata with hints
            teammate_names: Optional list of known system user names

        Returns:
            Extracted entities including company, contacts, signals
        """
        await self.ensure_orchestrator_exists()

        # Build extraction prompt
        prompt = get_entity_extraction_prompt(
            transcript=transcript,
            caller_email=metadata.caller_email if metadata else None,
            company_hint=metadata.company_hint if metadata else None,
            contact_hints=metadata.contact_hints if metadata else None,
            teammate_names=teammate_names,
        )

        # Create a thread for this extraction
        thread = await self._backboard.create_thread(self._assistant_id)

        # Send the extraction request
        response = await self._backboard.send_message(
            thread_id=thread.thread_id,
            content=prompt,
            memory="off",  # Don't store extraction requests in memory
        )

        # Get content from response (handle different response formats)
        if hasattr(response, "content"):
            content = response.content or ""
        elif isinstance(response, dict):
            content = response.get("content", "")
        else:
            content = str(response) if response else ""

        # Parse the response
        try:
            # Try to extract JSON from response
            # Find JSON in response
            json_match = re.search(r"\{[\s\S]*\}", content) if content else None
            if json_match:
                data = json.loads(json_match.group())
                
                # Parse contacts from response
                contacts = []
                for c in data.get("contacts", []):
                    if isinstance(c, dict) and c.get("name"):
                        contacts.append(StakeholderMention(
                            name=c.get("name"),
                            role=c.get("role"),
                            company=c.get("company"),
                            email=c.get("email"),
                            sentiment=c.get("sentiment"),
                            context=c.get("context"),
                            preferred_contact_method=self._normalize_contact_method(
                                c.get("preferred_contact_method")
                            ),
                        ))
                
                company_name = self._sanitize_company_name(data.get("company_name"))
                if not company_name:
                    company_name = await self._extract_company_name_only(transcript)

                return EntityExtraction(
                    company_name=company_name,
                    company_domain=data.get("company_domain"),
                    contacts=contacts,
                    signals=data.get("signals", []),
                    confidence=data.get("confidence", 0.5),
                    lead_source=data.get("lead_source"),
                    lead_source_detail=data.get("lead_source_detail"),
                )
        except (json.JSONDecodeError, AttributeError):
            pass

        # Return empty extraction on failure
        return EntityExtraction(
            company_name=self._sanitize_company_name(
                await self._extract_company_name_only(transcript)
            ),
            confidence=0.0,
        )

    async def segment_transcript_by_customer(
        self,
        transcript: str,
        metadata: TranscriptMetadata | None = None,
        teammate_names: list[str] | None = None,
    ) -> MultiCustomerSegmentation:
        """Split a brain dump into per-customer segments."""
        await self.ensure_orchestrator_exists()

        prompt = get_multi_customer_segment_prompt(transcript, teammate_names=teammate_names)
        thread = await self._backboard.create_thread(self._assistant_id)
        response = await self._backboard.send_message(
            thread_id=thread.thread_id,
            content=prompt,
            memory="off",
        )

        if hasattr(response, "content"):
            content = response.content or ""
        elif isinstance(response, dict):
            content = response.get("content", "")
        else:
            content = str(response) if response else ""

        fallback_company = metadata.company_hint if metadata else None
        fallback_contacts = metadata.contact_hints if metadata else []
        fallback = MultiCustomerSegmentation(
            segments=[
                MultiCustomerSegment(
                    company_name=fallback_company,
                    transcript=transcript,
                    contact_hints=fallback_contacts,
                    confidence=0.3,
                    rationale="Fallback segmentation",
                )
            ],
            overall_confidence=0.3,
        )

        if not content:
            return fallback

        try:
            json_match = re.search(r"\{[\s\S]*\}", content)
            if not json_match:
                return fallback
            data = json.loads(json_match.group())
            segmentation = MultiCustomerSegmentation.model_validate(data)
            if not segmentation.segments:
                return fallback
            return segmentation
        except Exception:
            return fallback

    async def _extract_company_name_only(self, transcript: str) -> str | None:
        """Extract company name using a focused LLM prompt."""
        await self.ensure_orchestrator_exists()

        prompt = get_company_name_prompt(transcript=transcript)
        thread = await self._backboard.create_thread(self._assistant_id)
        response = await self._backboard.send_message(
            thread_id=thread.thread_id,
            content=prompt,
            memory="off",
        )

        if hasattr(response, "content"):
            content = response.content or ""
        elif isinstance(response, dict):
            content = response.get("content", "")
        else:
            content = str(response) if response else ""

        company_name = None
        parsed_json = False
        try:
            json_match = re.search(r"\{[\s\S]*\}", content) if content else None
            if json_match:
                data = json.loads(json_match.group())
                company_name = data.get("company_name")
                parsed_json = True
        except (json.JSONDecodeError, AttributeError):
            pass

        if parsed_json:
            return self._sanitize_company_name(company_name)

        if not company_name:
            cleaned = content.strip().strip("\"'")
            if cleaned and cleaned.lower() not in {"null", "none"}:
                company_name = cleaned

        return self._sanitize_company_name(company_name)

    def _sanitize_company_name(self, company_name: str | None) -> str | None:
        """Guard against LLM error strings or unusable values."""
        if not company_name:
            return None

        cleaned = company_name.strip()
        if not cleaned:
            return None

        lowered = cleaned.lower()
        if any(
            marker in lowered
            for marker in (
                "llm-invocation-error",
                "chatprompttemplate",
                "missing variables",
                "troubleshooting",
            )
        ):
            return None

        # Reject raw JSON blobs that leaked through (e.g. '{"company_name": null}')
        if cleaned.startswith("{") and cleaned.endswith("}"):
            return None

        if len(cleaned) > 120:
            return None

        return cleaned

    def _normalize_contact_method(self, raw_method: Any) -> "ContactMethod | None":
        """Normalize preferred contact method values."""
        from app.schemas.enums import ContactMethod

        if isinstance(raw_method, ContactMethod):
            return raw_method
        if not raw_method:
            return None
        if not isinstance(raw_method, str):
            return None

        normalized = raw_method.strip().lower()
        method_map = {
            "email": ContactMethod.EMAIL,
            "text": ContactMethod.TEXT,
            "sms": ContactMethod.TEXT,
            "call": ContactMethod.CALL,
            "phone": ContactMethod.CALL,
            "whatsapp": ContactMethod.WHATSAPP,
        }
        return method_map.get(normalized)

    async def find_or_create_customer(
        self,
        company_name: str,
        company_domain: str | None = None,
        industry: str | None = None,
    ) -> tuple[str, bool]:
        """Find an existing customer or create a new one.

        Args:
            company_name: The company name
            company_domain: Optional company domain
            industry: Optional industry

        Returns:
            Tuple of (customer_assistant_id, is_new_customer)
        """
        await self.ensure_orchestrator_exists()

        normalized_name = self._normalize_company_name(company_name)

        # Check registry for existing customer
        if normalized_name in self._customer_registry:
            return self._customer_registry[normalized_name], False

        # Also check by domain if provided
        if company_domain:
            for name, assistant_id in self._customer_registry.items():
                # This is a simplified check - in production, store domains too
                if company_domain.lower() in name:
                    return assistant_id, False

        # No existing customer found - will need to create one
        # The actual creation is delegated to CustomerService
        # Here we just return None to indicate creation is needed
        return "", True

    async def register_customer(
        self,
        company_name: str,
        assistant_id: str,
    ) -> None:
        """Register a new customer in the orchestrator registry.

        Creates a single small memory for this customer (sharded approach).

        Args:
            company_name: The company name
            assistant_id: The customer's assistant ID
        """
        normalized = self._normalize_company_name(company_name)
        self._customer_registry[normalized] = assistant_id
        await self._save_single_registration(normalized, assistant_id)
        self._cache.invalidate_by_tag("registry")

    async def unregister_customer(self, assistant_id: str) -> bool:
        """Remove a customer from the registry by assistant ID.

        Deletes the matching ``customer_registration`` memory from Backboard.

        Args:
            assistant_id: The customer's assistant ID

        Returns:
            True if a registry entry was removed
        """
        await self.ensure_orchestrator_exists()

        # Remove from in-memory dict
        removed = False
        for name, aid in list(self._customer_registry.items()):
            if aid == assistant_id:
                del self._customer_registry[name]
                removed = True

        if not removed:
            return False

        # Delete the matching memory from Backboard
        try:
            memories = await self._backboard.get_memories(self._assistant_id)
            for memory in memories.memories:
                try:
                    data = json.loads(memory.content)
                    if (
                        data.get("type") == "customer_registration"
                        and data.get("assistant_id") == assistant_id
                    ):
                        memory_id = (
                            getattr(memory, "memory_id", None)
                            or getattr(memory, "id", None)
                        )
                        if memory_id:
                            await self._backboard.delete_memory(
                                self._assistant_id, str(memory_id),
                            )
                        break
                except (json.JSONDecodeError, KeyError):
                    continue
        except Exception:
            pass  # In-memory state is already updated; next load will reconcile

        self._cache.invalidate_by_tag("registry")
        return True

    async def get_all_customers(self) -> list[dict[str, str]]:
        """Get all registered customers.

        Returns:
            List of {company_name, assistant_id} dicts
        """
        await self.ensure_orchestrator_exists()
        cache_key = build_cache_key("registry", "all")

        async def _build():
            return [
                {"company_name": name, "assistant_id": aid}
                for name, aid in self._customer_registry.items()
            ]

        return await self._cache.get_or_set(
            cache_key,
            self._cache.with_jitter(CACHE_TTLS["registry"]),
            _build,
            tags=["registry"],
        )

    async def route_transcript(
        self,
        transcript: str,
        metadata: TranscriptMetadata | None = None,
        teammate_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Route a transcript to the appropriate customer.

        This is the main entry point for transcript processing.

        Args:
            transcript: The meeting transcript
            metadata: Optional metadata with hints
            teammate_names: Optional list of known system user names

        Returns:
            Routing decision with customer info and extracted entities
        """
        # Extract entities from transcript
        entities = await self.extract_entities(transcript, metadata, teammate_names=teammate_names)

        # Determine company name from extraction or hints
        company_name = entities.company_name
        if not company_name and metadata and metadata.company_hint:
            company_name = metadata.company_hint

        if not company_name:
            return {
                "action": "need_clarification",
                "reason": "Could not determine customer company from transcript",
                "entities": entities.model_dump(),
            }

        # Find or create customer
        assistant_id, is_new = await self.find_or_create_customer(
            company_name=company_name,
            company_domain=entities.company_domain,
        )

        return {
            "action": "create_customer" if is_new else "route_to_customer",
            "company_name": company_name,
            "company_domain": entities.company_domain,
            "customer_assistant_id": assistant_id if not is_new else None,
            "is_new_customer": is_new,
            "entities": entities.model_dump(),
        }


# Module-level singleton
_orchestrator_instance: OrchestratorService | None = None


async def get_orchestrator_service() -> OrchestratorService:
    """Get the orchestrator service singleton.

    Returns:
        OrchestratorService instance
    """
    global _orchestrator_instance
    if _orchestrator_instance is None:
        async with get_backboard_service() as backboard:
            _orchestrator_instance = OrchestratorService(backboard)
            await _orchestrator_instance.ensure_orchestrator_exists()
    return _orchestrator_instance


def get_orchestrator_service_sync(backboard: BackboardService) -> OrchestratorService:
    """Get an orchestrator service instance for sync contexts.

    Args:
        backboard: BackboardService instance to use

    Returns:
        OrchestratorService instance
    """
    return OrchestratorService(backboard)
