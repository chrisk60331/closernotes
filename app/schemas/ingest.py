"""Schemas for multi-customer ingest and bulk reports."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.meeting import TranscriptMetadata


class ReportType(str, Enum):
    """Supported ingest report types."""

    MULTI_TRANSCRIPT = "multi_transcript"
    CSV_BULK = "csv_bulk"


class MultiCustomerSegment(BaseModel):
    """A per-customer segment extracted from a brain dump."""

    company_name: str | None = Field(None, description="Detected customer company name")
    transcript: str = Field(..., min_length=10, description="Transcript chunk for this customer")
    contact_hints: list[str] = Field(
        default_factory=list, description="People mentioned for this customer"
    )
    company_domain: str | None = Field(None, description="Detected company domain")
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="Segment confidence")
    rationale: str | None = Field(None, description="Why this segment was assigned")


class MultiCustomerSegmentation(BaseModel):
    """Result of splitting a transcript into per-customer segments."""

    segments: list[MultiCustomerSegment] = Field(default_factory=list)
    overall_confidence: float = Field(0.5, ge=0.0, le=1.0)


class MultiIngestRequest(BaseModel):
    """Request payload for multi-customer transcript ingestion."""

    transcript: str = Field(..., min_length=10, description="Raw brain dump transcript")
    metadata: TranscriptMetadata = Field(
        default_factory=TranscriptMetadata, description="Optional metadata"
    )


class IngestReportItem(BaseModel):
    """Per-item outcome for multi-customer or bulk ingest."""

    index: int = Field(..., description="0-based index in source input")
    company_name: str | None = Field(None, description="Resolved company name")
    customer_id: str | None = Field(None, description="Customer ID if resolved")
    assistant_id: str | None = Field(None, description="Customer assistant ID")
    meeting_id: str | None = Field(None, description="Meeting/thread ID if created")
    is_new_customer: bool | None = Field(None, description="Whether customer was created")
    summary: str | None = Field(None, description="Short meeting summary if available")
    crm_updates: dict[str, Any] = Field(default_factory=dict)
    source: dict[str, Any] | None = Field(
        None, description="Source data (csv row, segment hints, etc.)"
    )
    error: str | None = Field(None, description="Error message if failed")


class IngestReport(BaseModel):
    """Stored report for multi-customer or bulk ingest operations."""

    report_id: str = Field(..., description="Unique report ID")
    report_type: ReportType = Field(..., description="Report type identifier")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    total_items: int = Field(..., ge=0)
    success_count: int = Field(..., ge=0)
    error_count: int = Field(..., ge=0)
    items: list[IngestReportItem] = Field(default_factory=list)
    source_label: str | None = Field(None, description="Label for the source input")
    followups: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Follow-up entries created during ingest",
    )
