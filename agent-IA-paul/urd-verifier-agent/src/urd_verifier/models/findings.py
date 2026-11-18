"""Finding, Diff Classification, Localization, and HITL Audit models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field

from .document import BoundingBox


class DiffCategory(str, Enum):
    """High-level classification of V0 vs V1 differences."""

    FORME = "forme"  # Font, size, bold/italic, color, spacing, layout, punctuation
    CONTENU = "contenu"  # Narrative text wording, semantic edits
    CHIFFRAGE = "chiffrage"  # Numerical figures, totals, percentages, units
    STRUCTURE = "structure"  # Added/removed/reordered sections, tables, pages
    METADONNEES = "metadonnees"  # Dates, headers/footers, version tags, titles
    REGLEMENTAIRE_ESEF = "reglementaire_esef"  # AMF concordance, ESEF/iXBRL, CSRD tags
    VISUEL_GRAPHIQUE = "visuel_graphique"  # Charts, bar/pie labels, images
    AJOUT = "ajout"  # Content present only in V1
    SUPPRESSION = "suppression"  # Content removed between V0 and V1


class ControlType(str, Enum):
    """Exact taxonomy of the 15 URD control/error types + version diff types."""

    # 100 % Automatisable (1 - 6)
    ARITHMETIQUE_TABLEAUX = "arithmetique_tableaux"
    CALCULS_VARIATIONS = "calculs_variations"
    RENVOIS_CONCORDANCE = "renvois_concordance"
    COMPARATIF_N_1_BRUT = "comparatif_n_1_brut"
    HYGIENE_DOCUMENTAIRE = "hygiene_documentaire"
    CONFORMITE_ESEF = "conformite_esef"

    # Semi-automatisable : IA + Humain (7 - 11)
    CROSS_CHECKS_INTER_SECTIONS = "cross_checks_inter_sections"
    COHERENCE_TEXTE_TABLEAU = "coherence_texte_tableau"
    UNITES_ECHELLES = "unites_echelles"
    GRAPHIQUES_VS_TABLEAUX = "graphiques_vs_tableaux"
    LIEN_FINANCE_CSRD = "lien_finance_csrd"

    # Human Check obligatoire (12 - 15)
    VALIDATION_RETRAITEMENTS_N_1 = "validation_retraitements_n_1"
    MATERIALITE_TOLERANCE = "materialite_tolerance"
    EXHAUSTIVITE_RISQUES = "exhaustivite_risques"
    TON_NON_TROMPEUR = "ton_non_trompeur"

    # Version comparison specific
    DIFF_V0_V1 = "diff_v0_v1"
    CONTRADICTION_V0_V1 = "contradiction_v0_v1"


class AutomationLevel(str, Enum):
    AUTO_100 = "auto_100"
    SEMI_AUTO_AI_HUMAN = "semi_auto_ai_human"
    HUMAN_MANDATORY = "human_mandatory"


class Severity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


class HITLStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    CONFIRMED_ERROR = "confirmed_error"
    ACCEPTED_CHANGE = "accepted_change"
    FALSE_POSITIVE = "false_positive"
    NEEDS_CLARIFICATION = "needs_clarification"


class LocationRef(BaseModel):
    """Exact spatial & logical anchor inside a PDF for UI highlighting."""

    doc_role: str  # "v0" | "v1" | "urd_n_minus_1"
    filename: str
    page_number: int
    page_width: float = 595.0
    page_height: float = 842.0
    bbox: BoundingBox
    section_title: str | None = None
    table_id: str | None = None
    cell_ref: str | None = None  # e.g., "row=3,col=2"
    quoted_text: str = ""


class AuditAction(BaseModel):
    """Immutable log entry of a human reviewer or agent action on a finding."""

    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    actor: str  # "agent" | "auditor:<name>"
    action: str
    previous_status: HITLStatus | None = None
    new_status: HITLStatus | None = None
    comment: str = ""


class Finding(BaseModel):
    """Unified representation of a detected diff, contradiction, or control error."""

    finding_id: str
    title: str
    description: str
    diff_category: DiffCategory
    control_type: ControlType
    automation_level: AutomationLevel
    severity: Severity

    # Values / diff details
    v0_value: str | None = None
    v1_value: str | None = None
    expected_value: str | None = None
    numeric_delta: float | None = None
    percent_delta: float | None = None

    # Exact coordinates in V0 and/or V1 (so the UI can highlight both sides)
    v0_location: LocationRef | None = None
    v1_location: LocationRef | None = None
    extra_locations: list[LocationRef] = Field(default_factory=list)

    # AI / Agent explanation & Human-in-the-loop prompt
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    ai_rationale: str = ""
    human_prompt: str = ""  # What the auditor specifically needs to verify
    requires_human_action: bool = False

    # HITL State
    hitl_status: HITLStatus = HITLStatus.PENDING_REVIEW
    reviewer_comment: str = ""
    is_material: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    audit_trail: list[AuditAction] = Field(default_factory=list)
