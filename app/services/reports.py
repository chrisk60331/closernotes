"""Report storage service using Backboard memory."""

from __future__ import annotations

import json
from typing import Any

from app.schemas.ingest import IngestReport, IngestReportItem
from app.services.backboard import BackboardService
from app.services.orchestrator import OrchestratorService


class ReportService:
    """Store and retrieve ingest reports from Backboard memory.

    Reports are split across multiple Backboard memories to stay within
    the 4 KB per-attribute filtering limit:

    * One ``ingest_report`` memory holds the header (stats, followups)
      with an empty ``items`` list.
    * One ``ingest_report_item`` memory per item, tagged with the same
      ``report_id``.

    ``get_report`` reassembles the full report from both.
    """

    def __init__(self, backboard: BackboardService):
        self._backboard = backboard
        self._orchestrator = OrchestratorService(backboard)

    async def store_report(self, report: IngestReport) -> str:
        """Persist a report in orchestrator memory (chunked)."""
        assistant_id = await self._orchestrator.ensure_orchestrator_exists()

        # 1) Header memory — everything except items
        header = report.model_dump(mode="json")
        header["items"] = []  # items stored separately

        await self._backboard.add_memory(
            assistant_id=assistant_id,
            content=json.dumps({
                "type": "ingest_report",
                "report_id": report.report_id,
                "header": header,
            }),
            metadata={
                "type": "ingest_report",
                "report_id": report.report_id,
                "report_type": report.report_type.value,
            },
        )

        # 2) One memory per item
        for item in report.items:
            await self._backboard.add_memory(
                assistant_id=assistant_id,
                content=json.dumps({
                    "type": "ingest_report_item",
                    "report_id": report.report_id,
                    "item": item.model_dump(mode="json"),
                }),
                metadata={
                    "type": "ingest_report_item",
                    "report_id": report.report_id,
                },
            )

        return report.report_id

    async def get_report(self, report_id: str) -> IngestReport | None:
        """Load a report by ID, reassembling header + items."""
        assistant_id = await self._orchestrator.ensure_orchestrator_exists()
        try:
            memories = await self._backboard.get_memories(assistant_id)
        except Exception:
            return None

        header_data: dict | None = None
        item_dicts: list[dict] = []

        for memory in getattr(memories, "memories", []):
            try:
                data = json.loads(memory.content)
            except (json.JSONDecodeError, AttributeError, TypeError):
                continue

            if not isinstance(data, dict):
                continue

            rid = data.get("report_id")
            if rid != report_id:
                continue

            mtype = data.get("type")

            # --- new chunked format ---
            if mtype == "ingest_report" and "header" in data:
                header_data = data["header"]
                continue

            if mtype == "ingest_report_item" and "item" in data:
                item_dicts.append(data["item"])
                continue

            # --- legacy formats (single-memory reports) ---
            if mtype == "ingest_report":
                # double-encoded string
                rds = data.get("report_data")
                if isinstance(rds, str):
                    try:
                        return IngestReport.model_validate(json.loads(rds))
                    except Exception:
                        pass
                # nested dict
                rd = data.get("report")
                if isinstance(rd, dict):
                    try:
                        return IngestReport.model_validate(rd)
                    except Exception:
                        pass

            # bare legacy
            if data.get("report_type"):
                try:
                    return IngestReport.model_validate(data)
                except Exception:
                    continue

        if header_data is not None:
            header_data["items"] = sorted(
                item_dicts, key=lambda x: x.get("index", 0)
            )
            return IngestReport.model_validate(header_data)

        return None

    async def list_reports(self) -> list[dict[str, Any]]:
        """List report metadata (best effort)."""
        assistant_id = await self._orchestrator.ensure_orchestrator_exists()
        try:
            memories = await self._backboard.get_memories(assistant_id)
        except Exception:
            return []

        results: list[dict[str, Any]] = []
        for memory in getattr(memories, "memories", []):
            try:
                data = json.loads(memory.content)
            except (json.JSONDecodeError, AttributeError, TypeError):
                continue

            if isinstance(data, dict) and data.get("type") == "ingest_report":
                header = data.get("header", {})
                results.append(
                    {
                        "report_id": data.get("report_id"),
                        "report_type": header.get("report_type")
                            or data.get("report", {}).get("report_type"),
                        "created_at": header.get("created_at")
                            or data.get("report", {}).get("created_at"),
                    }
                )
        return results
