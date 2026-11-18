"""Refines diff classification into URD error taxonomy, severity, and HITL routing."""

from __future__ import annotations

import re
import uuid

from urd_verifier.config import VerifierSettings
from urd_verifier.models.document import ParsedPDF
from urd_verifier.models.findings import (
    AutomationLevel,
    ControlType,
    DiffCategory,
    Finding,
    LocationRef,
    Severity,
)

_RISK_RE = re.compile(
    r"(?i)\b(risque|litige|contentieux|dépréciation|provision|amende|sinistre|cyber|défaillance)\b"
)
_RESTATEMENT_RE = re.compile(
    r"(?i)\b(ifrs\s*5|retraitement|retraité|pro\s*forma|changement\s+de\s+méthode|activités?\s+abandonnées?)\b"
)
_CSRD_RE = re.compile(
    r"(?i)\b(csrd|esrs|taxonomie|capex\s+vert|scope\s*[123]|émissions?\s+co2|effectifs?\s+etp|durabilité|esg)\b"
)
_ESEF_RE = re.compile(r"(?i)\b(ixbrl|xbrl|esef|esma|balisage|tag)\b")
_TONE_RE = re.compile(
    r"(?i)\b(leader\s+mondial|neutre\s+en\s+carbone|zéro\s+émission|sans\s+risque|garanti|exceptionnel|record|ajusté|iap|ebitda\s+ajusté)\b"
)


class DiffClassifier:
    """Enriches diff findings with domain-specific URD classification and HITL rules."""

    def __init__(self, settings: VerifierSettings) -> None:
        self.settings = settings

    def classify_header_diffs(
        self,
        v0: ParsedPDF,
        v1: ParsedPDF,
        header_diffs: list[tuple[int, str, str]],
    ) -> list[Finding]:
        findings: list[Finding] = []
        for page_num, h0, h1 in header_diffs:
            p0 = v0.pages[page_num - 1]
            p1 = v1.pages[page_num - 1]
            h0_blk = next((b for b in p0.blocks if b.block_type == "header"), None)
            h1_blk = next((b for b in p1.blocks if b.block_type == "header"), None)
            findings.append(
                Finding(
                    finding_id=f"hdr_{uuid.uuid4().hex[:10]}",
                    title=f"En-tête / métadonnée de page modifiée (p.{page_num})",
                    description=f"En-tête V0='{h0}' -> V1='{h1}'",
                    diff_category=DiffCategory.METADONNEES,
                    control_type=ControlType.HYGIENE_DOCUMENTAIRE,
                    automation_level=AutomationLevel.AUTO_100,
                    severity=Severity.INFO,
                    v0_value=h0,
                    v1_value=h1,
                    v0_location=(
                        LocationRef(
                            doc_role="v0",
                            filename=v0.filename,
                            page_number=page_num,
                            page_width=p0.width,
                            page_height=p0.height,
                            bbox=h0_blk.bbox,
                            quoted_text=h0,
                        )
                        if h0_blk
                        else None
                    ),
                    v1_location=(
                        LocationRef(
                            doc_role="v1",
                            filename=v1.filename,
                            page_number=page_num,
                            page_width=p1.width,
                            page_height=p1.height,
                            bbox=h1_blk.bbox,
                            quoted_text=h1,
                        )
                        if h1_blk
                        else None
                    ),
                    confidence=0.98,
                )
            )
        return findings

    def refine(self, findings: list[Finding]) -> list[Finding]:
        for f in findings:
            combined_text = " ".join(
                filter(
                    None,
                    [
                        f.title,
                        f.description,
                        f.v0_value,
                        f.v1_value,
                        f.v0_location.section_title if f.v0_location else "",
                        f.v1_location.section_title if f.v1_location else "",
                    ],
                )
            )

            # Tag ESEF/regulatory diffs
            if _ESEF_RE.search(combined_text):
                f.diff_category = DiffCategory.REGLEMENTAIRE_ESEF
                if f.control_type == ControlType.DIFF_V0_V1:
                    f.control_type = ControlType.CONFORMITE_ESEF

            # Detect N-1 restatement / IFRS 5 changes -> Mandatory Human Check
            col_hdr = str(f.metadata.get("col_header", "")).lower()
            is_n_minus_1_col = any(
                k in col_hdr for k in ("n-1", "2024", "retraité", "publié")
            )
            if (
                f.diff_category == DiffCategory.CHIFFRAGE
                and (is_n_minus_1_col or _RESTATEMENT_RE.search(combined_text))
                and f.control_type == ControlType.DIFF_V0_V1
            ):
                f.control_type = ControlType.VALIDATION_RETRAITEMENTS_N_1
                f.automation_level = AutomationLevel.HUMAN_MANDATORY
                f.severity = Severity.CRITICAL
                f.requires_human_action = True
                f.human_prompt = (
                    "Écart détecté sur une donnée N-1 / retraitée entre V0 et V1. "
                    "Jugement comptable obligatoire : vérifier si l'écart résulte d'une norme (ex. IFRS 5) "
                    "ou d'un changement de méthode et s'il est dûment expliqué en annexe."
                )

            # Detect CSRD / Sustainability modifications
            elif _CSRD_RE.search(combined_text) and f.control_type == ControlType.DIFF_V0_V1:
                if f.diff_category == DiffCategory.CHIFFRAGE:
                    f.control_type = ControlType.LIEN_FINANCE_CSRD
                    f.automation_level = AutomationLevel.SEMI_AUTO_AI_HUMAN
                    f.requires_human_action = True
                    f.human_prompt = (
                        "Donnée CSRD/Taxonomie modifiée entre V0 et V1 : vérifier le lien avec la section financière et les périmètres."
                    )

            # Detect Risk / Litigation / Impairment edits -> Mandatory Human Check
            elif _RISK_RE.search(combined_text) and f.diff_category in {
                DiffCategory.CONTENU,
                DiffCategory.SUPPRESSION,
                DiffCategory.CHIFFRAGE,
            }:
                if f.control_type == ControlType.DIFF_V0_V1:
                    f.control_type = ControlType.EXHAUSTIVITE_RISQUES
                    f.automation_level = AutomationLevel.HUMAN_MANDATORY
                    f.severity = Severity.MAJOR
                    f.requires_human_action = True
                    f.human_prompt = (
                        "Modification détectée sur les facteurs de risques / litiges / dépréciations. "
                        "Validation humaine obligatoire avec le dossier d'audit."
                    )

            # Detect Tone / Greenwashing / IAP bias shifts -> Mandatory Human Check
            elif _TONE_RE.search(combined_text) and f.diff_category in {
                DiffCategory.CONTENU,
                DiffCategory.AJOUT,
            }:
                if f.control_type == ControlType.DIFF_V0_V1:
                    f.control_type = ControlType.TON_NON_TROMPEUR
                    f.automation_level = AutomationLevel.HUMAN_MANDATORY
                    f.severity = Severity.MAJOR
                    f.requires_human_action = True
                    f.human_prompt = (
                        "Évolution de formulation liée aux IAP ou allégations ESG. "
                        "Appréciation qualitative obligatoire du caractère non trompeur."
                    )

            # Materiality annotation for minor numeric diffs
            if (
                f.diff_category == DiffCategory.CHIFFRAGE
                and f.percent_delta is not None
                and abs(f.percent_delta) < self.settings.materiality_threshold_pct
                and f.control_type == ControlType.DIFF_V0_V1
            ):
                f.is_material = False
                if f.severity == Severity.MAJOR:
                    f.severity = Severity.MINOR
                f.metadata["materiality_note"] = (
                    f"Variation faible ({f.percent_delta:+.2f} % < seuil {self.settings.materiality_threshold_pct} %) : "
                    "soumis à appréciation de matérialité avant dépôt AMF."
                )

        return findings
