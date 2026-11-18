"""Mandatory Human-in-the-Loop (HITL) control points (Controls 12 to 15 from taxonomy)."""

from __future__ import annotations

import re
import uuid

from urd_verifier.agent.llm_client import LLMClient
from urd_verifier.config import VerifierSettings
from urd_verifier.models.document import ParsedPDF
from urd_verifier.models.findings import (
    AutomationLevel,
    ControlType,
    DiffCategory,
    Finding,
    Severity,
)
from .base import BaseCheckRunner, make_block_loc

_RESTATEMENT_RE = re.compile(
    r"(?i)\b(ifrs\s*5|retraitement|retrait[eé]e?s?|changement\s+de\s+m[eé]thode|activit[eé]s?\s+abandonn[eé]es?|pro\s*forma)\b"
)
_RISK_RE = re.compile(
    r"(?i)\b(facteurs?\s+de\s+risques?|litiges?|contentieux|d[eé]pr[eé]ciations?|provisions?\s+pour\s+risques?)\b"
)
_GREENWASHING_IAP_RE = re.compile(
    r"(?i)\b(neutre\s+en\s+carbone|z[eé]ro\s+[eé]mission|100\s*%\s+durable|sans\s+impact|"
    r"performance\s+exceptionnelle|croissance\s+record|ebitda\s+ajust[eé]|indicateurs?\s+alternatifs?\s+de\s+performance|iap)\b"
)


class HumanMandatoryChecks(BaseCheckRunner):
    """Generates localized mandatory Human Checkpoints for controls 12-15."""

    def __init__(self, settings: VerifierSettings, llm: LLMClient) -> None:
        self.settings = settings
        self.llm = llm

    def run(
        self,
        v0: ParsedPDF,
        v1: ParsedPDF,
        urd_n_minus_1: ParsedPDF | None = None,
    ) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._detect_restatement_checkpoints(v1))
        findings.extend(self._detect_risk_checkpoints(v1))
        findings.extend(self._detect_tone_greenwashing_checkpoints(v1))
        return findings

    # 12. Validation des retraitements N-1
    def _detect_restatement_checkpoints(self, v1: ParsedPDF) -> list[Finding]:
        findings: list[Finding] = []
        seen_pages: set[int] = set()
        for page in v1.pages:
            for blk in page.blocks:
                if blk.block_type in {"header", "footer"}:
                    continue
                m = _RESTATEMENT_RE.search(blk.text)
                if m and page.page_number not in seen_pages:
                    seen_pages.add(page.page_number)
                    findings.append(
                        Finding(
                            finding_id=f"hitl_rest_{uuid.uuid4().hex[:10]}",
                            title=f"Validation obligatoire : retraitement N-1 / '{m.group(0)}' (p.{page.page_number})",
                            description=f"Mention détectée en V1 : « {blk.text[:220]} »",
                            diff_category=DiffCategory.CHIFFRAGE,
                            control_type=ControlType.VALIDATION_RETRAITEMENTS_N_1,
                            automation_level=AutomationLevel.HUMAN_MANDATORY,
                            severity=Severity.MAJOR,
                            v1_value=m.group(0),
                            v1_location=make_block_loc(v1, blk, "v1"),
                            confidence=0.92,
                            human_prompt=(
                                "Jugement comptable obligatoire : valider que ce retraitement N-1 (norme IFRS 5 / changement de méthode) "
                                "est justifié, exact et clairement expliqué en annexe."
                            ),
                            requires_human_action=True,
                        )
                    )
                    break
        return findings

    # 13. Matérialité & tolérance (called on aggregated findings in orchestrator)
    def build_materiality_checkpoint(
        self, v1: ParsedPDF, minor_findings: list[Finding]
    ) -> list[Finding]:
        if not minor_findings or not v1.pages or not v1.pages[0].blocks:
            return []
        sample_loc = next(
            (f.v1_location for f in minor_findings if f.v1_location is not None),
            make_block_loc(v1, v1.pages[0].blocks[0], "v1"),
        )
        return [
            Finding(
                finding_id=f"hitl_mat_{uuid.uuid4().hex[:10]}",
                title=f"Appréciation de matérialité sur {len(minor_findings)} écart(s) mineur(s) avant dépôt AMF",
                description=(
                    f"{len(minor_findings)} écart(s) inférieur(s) au seuil de tolérance ({self.settings.materiality_threshold_pct} % / "
                    f"{self.settings.materiality_threshold_eur:,.0f} €) détecté(s). Décision requise : corriger ou accepter."
                ),
                diff_category=DiffCategory.CHIFFRAGE,
                control_type=ControlType.MATERIALITE_TOLERANCE,
                automation_level=AutomationLevel.HUMAN_MANDATORY,
                severity=Severity.MINOR,
                v1_location=sample_loc,
                confidence=0.95,
                human_prompt=(
                    "Appréciation du seuil de matérialité par l'auditeur : décider si ces écarts mineurs "
                    "doivent être corrigés avant le dépôt AMF."
                ),
                requires_human_action=True,
                metadata={"minor_finding_ids": [f.finding_id for f in minor_findings]},
            )
        ]

    # 14. Exhaustivité & fidélité des risques
    def _detect_risk_checkpoints(self, v1: ParsedPDF) -> list[Finding]:
        findings: list[Finding] = []
        seen_pages: set[int] = set()
        for page in v1.pages:
            for blk in page.blocks:
                if blk.block_type in {"header", "footer"}:
                    continue
                m = _RISK_RE.search(blk.text)
                if m and page.page_number not in seen_pages:
                    seen_pages.add(page.page_number)
                    findings.append(
                        Finding(
                            finding_id=f"hitl_risk_{uuid.uuid4().hex[:10]}",
                            title=f"Revue risques / litiges / dépréciations : '{m.group(0)}' (p.{page.page_number})",
                            description=f"Section sensible identifiée : « {blk.text[:220]} »",
                            diff_category=DiffCategory.CONTENU,
                            control_type=ControlType.EXHAUSTIVITE_RISQUES,
                            automation_level=AutomationLevel.HUMAN_MANDATORY,
                            severity=Severity.MAJOR,
                            v1_value=m.group(0),
                            v1_location=make_block_loc(v1, blk, "v1"),
                            confidence=0.90,
                            human_prompt=(
                                "Human Check obligatoire : croiser cette présentation des risques/litiges/dépréciations "
                                "avec le dossier d'audit et la connaissance du client pour vérifier l'exhaustivité."
                            ),
                            requires_human_action=True,
                        )
                    )
                    break
        return findings

    # 15. Ton & caractère non trompeur
    def _detect_tone_greenwashing_checkpoints(self, v1: ParsedPDF) -> list[Finding]:
        findings: list[Finding] = []
        seen_pages: set[int] = set()
        for page in v1.pages:
            for blk in page.blocks:
                if blk.block_type in {"header", "footer"}:
                    continue
                m = _GREENWASHING_IAP_RE.search(blk.text)
                if m and page.page_number not in seen_pages:
                    seen_pages.add(page.page_number)
                    findings.append(
                        Finding(
                            finding_id=f"hitl_tone_{uuid.uuid4().hex[:10]}",
                            title=f"Vérification ton / greenwashing / IAP : '{m.group(0)}' (p.{page.page_number})",
                            description=f"Formulation sensible détectée : « {blk.text[:220]} »",
                            diff_category=DiffCategory.CONTENU,
                            control_type=ControlType.TON_NON_TROMPEUR,
                            automation_level=AutomationLevel.HUMAN_MANDATORY,
                            severity=Severity.MAJOR,
                            v1_value=m.group(0),
                            v1_location=make_block_loc(v1, blk, "v1"),
                            confidence=0.89,
                            human_prompt=(
                                "Appréciation qualitative obligatoire du commissaire aux comptes : vérifier l'absence "
                                "de greenwashing, de discours excessivement optimiste ou de mise en avant biaisée d'IAP par rapport aux agrégats IFRS."
                            ),
                            requires_human_action=True,
                        )
                    )
                    break
        return findings
