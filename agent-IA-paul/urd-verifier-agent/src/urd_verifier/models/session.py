"""Session, Version Detection, and Human-in-the-Loop API contract models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field

from .document import BoundingBox
from .findings import (
    AutomationLevel,
    ControlType,
    DiffCategory,
    Finding,
    HITLStatus,
    Severity,
)


class VersionSignal(BaseModel):
    """Single clue used to determine which PDF is V0 and which is V1."""

    doc_filename: str
    signal_type: str  # filename | metadata_date | cover_version | cover_date | draft_marker | content_progression
    evidence: str
    favors: Literal["v0", "v1", "urd_n_minus_1", "neutral"]
    weight: float
    page_number: int | None = None
    bbox: BoundingBox | None = None


class VersionDetectionResult(BaseModel):
    """Result of automatic V0 vs V1 identification across uploaded PDFs."""

    v0_filename: str
    v1_filename: str
    urd_n_minus_1_filename: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    needs_human_confirmation: bool = False
    rationale: str
    signals: list[VersionSignal] = Field(default_factory=list)
    confirmed_by_human: bool = False


class SessionSummary(BaseModel):
    """Aggregated statistics for the UI dashboard."""

    total_findings: int = 0
    by_diff_category: dict[str, int] = Field(default_factory=dict)
    by_control_type: dict[str, int] = Field(default_factory=dict)
    by_automation_level: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_hitl_status: dict[str, int] = Field(default_factory=dict)
    pending_human_checks: int = 0
    confirmed_errors: int = 0
    accepted_changes: int = 0
    overall_readiness: Literal["ready", "review_required", "blocked_critical_errors"] = (
        "review_required"
    )


class HITLDecisionRequest(BaseModel):
    """Payload sent by the UI when an auditor reviews a finding."""

    auditor_name: str = "Auditeur"
    new_status: HITLStatus
    comment: str = ""
    is_material: bool | None = None
    override_severity: Severity | None = None


class VersionOverrideRequest(BaseModel):
    """Payload sent by the UI if the auditor swaps or confirms V0 / V1 assignment."""

    auditor_name: str = "Auditeur"
    v0_filename: str
    v1_filename: str
    urd_n_minus_1_filename: str | None = None


class VerificationSession(BaseModel):
    """Full persistent state of a V0 vs V1 URD verification run."""

    session_id: str
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    status: Literal[
        "created",
        "parsing",
        "version_detected",
        "verifying",
        "awaiting_human_review",
        "completed",
        "failed",
    ] = "created"
    progress_pct: int = 0
    current_step: str = ""
    error_message: str | None = None

    uploaded_files: dict[str, str] = Field(default_factory=dict)  # filename -> path
    version_detection: VersionDetectionResult | None = None

    # Metadata about parsed docs (page counts, section lists) for UI navigation
    doc_info: dict[str, dict] = Field(default_factory=dict)

    findings: list[Finding] = Field(default_factory=list)
    summary: SessionSummary = Field(default_factory=SessionSummary)
    executive_summary: str = ""
    annotated_v0_path: str | None = None
    annotated_v1_path: str | None = None
    agent_trace: list[str] = Field(default_factory=list)
