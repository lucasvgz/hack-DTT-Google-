"""Text, numeric-in-text, and visual style ('forme') diff engine between V0 and V1."""

from __future__ import annotations

import re
import uuid
from difflib import SequenceMatcher

from urd_verifier.ingestion.number_parser import extract_numbers_from_text
from urd_verifier.models.document import ParsedPDF, TextBlock
from urd_verifier.models.findings import (
    AutomationLevel,
    ControlType,
    DiffCategory,
    Finding,
    LocationRef,
    Severity,
)
from .aligner import AlignedPair


def _loc(doc: ParsedPDF, blk: TextBlock, role: str) -> LocationRef:
    page = doc.pages[blk.page_number - 1]
    return LocationRef(
        doc_role=role,
        filename=doc.filename,
        page_number=blk.page_number,
        page_width=page.width,
        page_height=page.height,
        bbox=blk.bbox,
        section_title=blk.section_title,
        quoted_text=blk.text[:350],
    )


def _strip_punct_ws(t: str) -> str:
    return re.sub(r"[\s\W_]+", "", t.lower())


def _style_summary(b: TextBlock) -> str:
    flags = []
    if b.is_bold:
        flags.append("Gras")
    if b.is_italic:
        flags.append("Italique")
    style = f"{b.primary_font} {b.primary_size:.1f}pt"
    if flags:
        style += f" ({', '.join(flags)})"
    if b.color_hex and b.color_hex != "#000000":
        style += f" {b.color_hex}"
    return style


def _word_diff_summary(t0: str, t1: str) -> str:
    w0 = t0.split()
    w1 = t1.split()
    sm = SequenceMatcher(None, w0, w1)
    parts: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            parts.append(f"[{' '.join(w0[i1:i2])} -> {' '.join(w1[j1:j2])}]")
        elif tag == "delete":
            parts.append(f"[- {' '.join(w0[i1:i2])}]")
        elif tag == "insert":
            parts.append(f"[+ {' '.join(w1[j1:j2])}]")
    return " ; ".join(parts[:6])


class TextDiffEngine:
    """Produces localized, classified findings from aligned V0 and V1 text blocks."""

    def diff(
        self,
        v0: ParsedPDF,
        v1: ParsedPDF,
        aligned_blocks: list[AlignedPair[TextBlock]],
    ) -> list[Finding]:
        findings: list[Finding] = []

        for pair in aligned_blocks:
            b0, b1 = pair.v0_item, pair.v1_item

            # Added in V1
            if b0 is None and b1 is not None:
                is_heading = b1.block_type == "heading"
                findings.append(
                    Finding(
                        finding_id=f"diff_{uuid.uuid4().hex[:10]}",
                        title=f"{'Nouvelle section' if is_heading else 'Ajout de contenu'} en V1 (p.{b1.page_number})",
                        description=f"Bloc présent uniquement en V1 : « {b1.text[:180]} »",
                        diff_category=DiffCategory.STRUCTURE if is_heading else DiffCategory.AJOUT,
                        control_type=ControlType.DIFF_V0_V1,
                        automation_level=AutomationLevel.AUTO_100,
                        severity=Severity.MINOR if not is_heading else Severity.MAJOR,
                        v0_value=None,
                        v1_value=b1.text[:500],
                        v1_location=_loc(v1, b1, "v1"),
                        confidence=0.95,
                        ai_rationale="Bloc détecté en V1 sans équivalent aligné en V0.",
                    )
                )
                continue

            # Removed from V0
            if b0 is not None and b1 is None:
                is_heading = b0.block_type == "heading"
                findings.append(
                    Finding(
                        finding_id=f"diff_{uuid.uuid4().hex[:10]}",
                        title=f"{'Section supprimée' if is_heading else 'Suppression de contenu'} par rapport à V0 (p.{b0.page_number})",
                        description=f"Bloc présent en V0 mais absent en V1 : « {b0.text[:180]} »",
                        diff_category=DiffCategory.STRUCTURE if is_heading else DiffCategory.SUPPRESSION,
                        control_type=ControlType.DIFF_V0_V1,
                        automation_level=AutomationLevel.SEMI_AUTO_AI_HUMAN,
                        severity=Severity.MAJOR if is_heading else Severity.MINOR,
                        v0_value=b0.text[:500],
                        v1_value=None,
                        v0_location=_loc(v0, b0, "v0"),
                        confidence=0.95,
                        ai_rationale="Contenu présent en V0 non retrouvé en V1.",
                        human_prompt="Vérifier que cette suppression par rapport à V0 est volontaire et n'omet pas une information obligatoire.",
                        requires_human_action=True,
                    )
                )
                continue

            assert b0 is not None and b1 is not None
            norm0 = " ".join(b0.text.split())
            norm1 = " ".join(b1.text.split())

            # Text differs
            if norm0 != norm1:
                nums0 = extract_numbers_from_text(norm0)
                nums1 = extract_numbers_from_text(norm1)
                vals0 = [n.value for n in nums0]
                vals1 = [n.value for n in nums1]

                if _strip_punct_ws(norm0) == _strip_punct_ws(norm1):
                    category = DiffCategory.FORME
                    severity = Severity.INFO
                    title = f"Différence de ponctuation / mise en forme (V0 p.{b0.page_number} / V1 p.{b1.page_number})"
                    delta = None
                    pct_delta = None
                elif vals0 != vals1 and (vals0 or vals1):
                    category = DiffCategory.CHIFFRAGE
                    severity = Severity.MAJOR
                    title = f"Chiffre modifié dans le texte (V0 p.{b0.page_number} -> V1 p.{b1.page_number})"
                    delta = None
                    pct_delta = None
                    if len(vals0) == len(vals1):
                        changed_pairs = [
                            (a, b) for a, b in zip(vals0, vals1) if abs(a - b) > 1e-6
                        ]
                        if len(changed_pairs) == 1:
                            a, b = changed_pairs[0]
                            delta = round(b - a, 4)
                            if a != 0:
                                pct_delta = round((delta / abs(a)) * 100.0, 2)
                else:
                    category = DiffCategory.CONTENU
                    severity = Severity.MINOR
                    title = f"Modification rédactionnelle (V0 p.{b0.page_number} -> V1 p.{b1.page_number})"
                    delta = None
                    pct_delta = None

                diff_summary = _word_diff_summary(norm0, norm1)
                findings.append(
                    Finding(
                        finding_id=f"diff_{uuid.uuid4().hex[:10]}",
                        title=title,
                        description=f"Écart détecté : {diff_summary}",
                        diff_category=category,
                        control_type=ControlType.DIFF_V0_V1,
                        automation_level=(
                            AutomationLevel.SEMI_AUTO_AI_HUMAN
                            if category in {DiffCategory.CHIFFRAGE, DiffCategory.CONTENU}
                            else AutomationLevel.AUTO_100
                        ),
                        severity=severity,
                        v0_value=norm0[:500],
                        v1_value=norm1[:500],
                        numeric_delta=delta,
                        percent_delta=pct_delta,
                        v0_location=_loc(v0, b0, "v0"),
                        v1_location=_loc(v1, b1, "v1"),
                        confidence=0.94,
                        ai_rationale=f"Alignement de blocs (similarité {pair.similarity:.0%}). Diff : {diff_summary}",
                        human_prompt=(
                            "Valider que cette modification chiffrée ou sémantique entre V0 et V1 est justifiée et cohérente avec les tableaux."
                            if category in {DiffCategory.CHIFFRAGE, DiffCategory.CONTENU}
                            else ""
                        ),
                        requires_human_action=(category == DiffCategory.CHIFFRAGE),
                    )
                )
            else:
                # Text is identical: check typographic / visual style ('forme') differences
                font_changed = (
                    b0.primary_font.split("+")[-1] != b1.primary_font.split("+")[-1]
                )
                size_changed = abs(b0.primary_size - b1.primary_size) >= 0.9
                weight_changed = (b0.is_bold != b1.is_bold) or (b0.is_italic != b1.is_italic)
                color_changed = b0.color_hex != b1.color_hex

                if font_changed or size_changed or weight_changed or color_changed:
                    s0 = _style_summary(b0)
                    s1 = _style_summary(b1)
                    findings.append(
                        Finding(
                            finding_id=f"form_{uuid.uuid4().hex[:10]}",
                            title=f"Différence de forme typographique (V0 p.{b0.page_number} / V1 p.{b1.page_number})",
                            description=f"Texte identique mais style modifié : {s0} -> {s1}",
                            diff_category=DiffCategory.FORME,
                            control_type=ControlType.DIFF_V0_V1,
                            automation_level=AutomationLevel.AUTO_100,
                            severity=Severity.INFO,
                            v0_value=s0,
                            v1_value=s1,
                            v0_location=_loc(v0, b0, "v0"),
                            v1_location=_loc(v1, b1, "v1"),
                            confidence=0.98,
                            ai_rationale="Changement de police, taille, graisse, italique ou couleur sur texte inchangé.",
                        )
                    )

        return findings
