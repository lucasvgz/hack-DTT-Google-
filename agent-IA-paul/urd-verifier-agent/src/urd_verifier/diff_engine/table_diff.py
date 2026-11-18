"""Cell-by-cell and structural diff engine for financial/ESG tables between V0 and V1."""

from __future__ import annotations

import uuid
from difflib import SequenceMatcher

from urd_verifier.models.document import ParsedPDF, TableCell, TableData
from urd_verifier.models.findings import (
    AutomationLevel,
    ControlType,
    DiffCategory,
    Finding,
    LocationRef,
    Severity,
)
from .aligner import AlignedPair


def _table_loc(
    doc: ParsedPDF,
    tbl: TableData,
    role: str,
    cell: TableCell | None = None,
) -> LocationRef:
    page = doc.pages[tbl.page_number - 1]
    bbox = (cell.bbox if cell and cell.bbox else tbl.bbox)
    cell_ref = f"row={cell.row_idx},col={cell.col_idx}" if cell else None
    quoted = cell.text if cell else (tbl.title or f"Tableau {tbl.table_id}")
    return LocationRef(
        doc_role=role,
        filename=doc.filename,
        page_number=tbl.page_number,
        page_width=page.width,
        page_height=page.height,
        bbox=bbox,
        section_title=tbl.section_title,
        table_id=tbl.table_id,
        cell_ref=cell_ref,
        quoted_text=quoted[:300],
    )


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


class TableDiffEngine:
    """Compares aligned V0 and V1 tables with exact cell-level localization."""

    def diff(
        self,
        v0: ParsedPDF,
        v1: ParsedPDF,
        aligned_tables: list[AlignedPair[TableData]],
    ) -> list[Finding]:
        findings: list[Finding] = []

        for pair in aligned_tables:
            t0, t1 = pair.v0_item, pair.v1_item

            if t0 is None and t1 is not None:
                findings.append(
                    Finding(
                        finding_id=f"tdiff_{uuid.uuid4().hex[:10]}",
                        title=f"Nouveau tableau en V1 : '{t1.title or t1.table_id}' (p.{t1.page_number})",
                        description=f"Tableau présent uniquement en V1 ({len(t1.rows)} lignes).",
                        diff_category=DiffCategory.STRUCTURE,
                        control_type=ControlType.DIFF_V0_V1,
                        automation_level=AutomationLevel.AUTO_100,
                        severity=Severity.MAJOR,
                        v1_value=t1.title or t1.table_id,
                        v1_location=_table_loc(v1, t1, "v1"),
                        confidence=0.95,
                    )
                )
                continue

            if t0 is not None and t1 is None:
                findings.append(
                    Finding(
                        finding_id=f"tdiff_{uuid.uuid4().hex[:10]}",
                        title=f"Tableau supprimé en V1 : '{t0.title or t0.table_id}' (V0 p.{t0.page_number})",
                        description=f"Tableau présent en V0 mais absent en V1 ({len(t0.rows)} lignes).",
                        diff_category=DiffCategory.SUPPRESSION,
                        control_type=ControlType.DIFF_V0_V1,
                        automation_level=AutomationLevel.SEMI_AUTO_AI_HUMAN,
                        severity=Severity.MAJOR,
                        v0_value=t0.title or t0.table_id,
                        v0_location=_table_loc(v0, t0, "v0"),
                        confidence=0.95,
                        human_prompt="Confirmer que la suppression de ce tableau est attendue.",
                        requires_human_action=True,
                    )
                )
                continue

            assert t0 is not None and t1 is not None
            label = t1.title or t0.title or t1.table_id

            # 1. Unit change check
            if t0.unit_hint != t1.unit_hint and (t0.unit_hint or t1.unit_hint):
                findings.append(
                    Finding(
                        finding_id=f"tdiff_{uuid.uuid4().hex[:10]}",
                        title=f"Changement d'unité sur tableau '{label}'",
                        description=f"Unité modifiée entre V0 ('{t0.unit_hint or 'aucune'}') et V1 ('{t1.unit_hint or 'aucune'}').",
                        diff_category=DiffCategory.CHIFFRAGE,
                        control_type=ControlType.UNITES_ECHELLES,
                        automation_level=AutomationLevel.SEMI_AUTO_AI_HUMAN,
                        severity=Severity.CRITICAL,
                        v0_value=t0.unit_hint or "non précisée",
                        v1_value=t1.unit_hint or "non précisée",
                        v0_location=_table_loc(v0, t0, "v0"),
                        v1_location=_table_loc(v1, t1, "v1"),
                        confidence=0.92,
                        human_prompt="Vérifier si les valeurs du tableau ont bien été converties à la nouvelle échelle (k€ / M€ / Md€).",
                        requires_human_action=True,
                    )
                )

            # 2. Header comparison (including column inversion detection)
            h0_norm = [_norm(h) for h in t0.headers]
            h1_norm = [_norm(h) for h in t1.headers]
            if h0_norm != h1_norm:
                is_inverted = (
                    len(h0_norm) == len(h1_norm)
                    and set(h0_norm) == set(h1_norm)
                    and len(h0_norm) >= 2
                )
                findings.append(
                    Finding(
                        finding_id=f"tdiff_{uuid.uuid4().hex[:10]}",
                        title=(
                            f"Colonnes inversées dans '{label}'"
                            if is_inverted
                            else f"En-têtes modifiés dans '{label}'"
                        ),
                        description=f"En-têtes V0: {t0.headers} vs V1: {t1.headers}",
                        diff_category=DiffCategory.METADONNEES,
                        control_type=(
                            ControlType.HYGIENE_DOCUMENTAIRE
                            if is_inverted
                            else ControlType.DIFF_V0_V1
                        ),
                        automation_level=AutomationLevel.AUTO_100,
                        severity=Severity.CRITICAL if is_inverted else Severity.MINOR,
                        v0_value=" | ".join(t0.headers),
                        v1_value=" | ".join(t1.headers),
                        v0_location=_table_loc(v0, t0, "v0"),
                        v1_location=_table_loc(v1, t1, "v1"),
                        confidence=0.96,
                        ai_rationale=(
                            "Les mêmes libellés de colonnes apparaissent dans un ordre inversé entre V0 et V1 (risque d'inversion N / N-1)."
                            if is_inverted
                            else "Modification des libellés d'en-tête du tableau."
                        ),
                    )
                )

            # 3. Row alignment by first column label
            rows0 = t0.rows[1:] if len(t0.rows) > 1 else []
            rows1 = t1.rows[1:] if len(t1.rows) > 1 else []
            used_r1: set[int] = set()

            for r0 in rows0:
                lbl0 = _norm(r0[0].text) if r0 else ""
                best_idx = -1
                best_sim = 0.0
                for idx1, r1 in enumerate(rows1):
                    if idx1 in used_r1:
                        continue
                    lbl1 = _norm(r1[0].text) if r1 else ""
                    if lbl0 == lbl1 and lbl0:
                        best_idx = idx1
                        best_sim = 1.0
                        break
                    sim = SequenceMatcher(None, lbl0, lbl1).ratio()
                    if sim > best_sim:
                        best_sim = sim
                        best_idx = idx1

                if best_idx >= 0 and best_sim >= 0.68:
                    used_r1.add(best_idx)
                    r1 = rows1[best_idx]
                    max_cols = min(len(r0), len(r1))
                    for c_idx in range(max_cols):
                        c0, c1 = r0[c_idx], r1[c_idx]
                        if _norm(c0.text) == _norm(c1.text):
                            continue
                        col_name = (
                            t1.headers[c_idx] if c_idx < len(t1.headers) else f"Col {c_idx}"
                        )
                        row_name = r1[0].text.strip() or r0[0].text.strip() or f"Ligne {r1[0].row_idx}"

                        if c0.numeric_value is not None and c1.numeric_value is not None:
                            delta = round(c1.numeric_value - c0.numeric_value, 4)
                            if abs(delta) < 1e-6:
                                # Same numeric value, only formatting differs
                                findings.append(
                                    Finding(
                                        finding_id=f"tdiff_{uuid.uuid4().hex[:10]}",
                                        title=f"Formatage modifié dans '{label}' ({row_name} / {col_name})",
                                        description=f"Valeur identique ({c1.numeric_value}) mais format changé : '{c0.text}' -> '{c1.text}'",
                                        diff_category=DiffCategory.FORME,
                                        control_type=ControlType.DIFF_V0_V1,
                                        automation_level=AutomationLevel.AUTO_100,
                                        severity=Severity.INFO,
                                        v0_value=c0.text,
                                        v1_value=c1.text,
                                        v0_location=_table_loc(v0, t0, "v0", c0),
                                        v1_location=_table_loc(v1, t1, "v1", c1),
                                        confidence=0.98,
                                    )
                                )
                                continue

                            pct_delta = (
                                round((delta / abs(c0.numeric_value)) * 100.0, 2)
                                if c0.numeric_value != 0
                                else None
                            )
                            findings.append(
                                Finding(
                                    finding_id=f"tdiff_{uuid.uuid4().hex[:10]}",
                                    title=f"Chiffre modifié dans '{label}' : {row_name} ({col_name})",
                                    description=(
                                        f"Écart sur '{row_name}' [{col_name}] : V0='{c0.text}' -> V1='{c1.text}' "
                                        f"(delta {delta:+.2f})"
                                    ),
                                    diff_category=DiffCategory.CHIFFRAGE,
                                    control_type=ControlType.DIFF_V0_V1,
                                    automation_level=AutomationLevel.SEMI_AUTO_AI_HUMAN,
                                    severity=Severity.MAJOR,
                                    v0_value=c0.text,
                                    v1_value=c1.text,
                                    numeric_delta=delta,
                                    percent_delta=pct_delta,
                                    v0_location=_table_loc(v0, t0, "v0", c0),
                                    v1_location=_table_loc(v1, t1, "v1", c1),
                                    confidence=0.97,
                                    ai_rationale="Modification de donnée chiffrée entre V0 et V1.",
                                    human_prompt="Confirmer la mise à jour du chiffre (correction d'audit, actualisation ou retraitement N-1) et vérifier sa répercussion dans le texte et les totaux.",
                                    requires_human_action=True,
                                    metadata={
                                        "row_label": row_name,
                                        "col_header": col_name,
                                        "unit": t1.unit_hint or t0.unit_hint,
                                    },
                                )
                            )
                        else:
                            findings.append(
                                Finding(
                                    finding_id=f"tdiff_{uuid.uuid4().hex[:10]}",
                                    title=f"Cellule modifiée dans '{label}' ({row_name} / {col_name})",
                                    description=f"V0='{c0.text}' -> V1='{c1.text}'",
                                    diff_category=DiffCategory.CONTENU,
                                    control_type=ControlType.DIFF_V0_V1,
                                    automation_level=AutomationLevel.AUTO_100,
                                    severity=Severity.MINOR,
                                    v0_value=c0.text,
                                    v1_value=c1.text,
                                    v0_location=_table_loc(v0, t0, "v0", c0),
                                    v1_location=_table_loc(v1, t1, "v1", c1),
                                    confidence=0.95,
                                )
                            )
                else:
                    row_label = r0[0].text.strip() if r0 else "Ligne"
                    findings.append(
                        Finding(
                            finding_id=f"tdiff_{uuid.uuid4().hex[:10]}",
                            title=f"Ligne supprimée dans '{label}' : '{row_label}'",
                            description=f"Ligne présente en V0 p.{t0.page_number} absente en V1.",
                            diff_category=DiffCategory.SUPPRESSION,
                            control_type=ControlType.DIFF_V0_V1,
                            automation_level=AutomationLevel.SEMI_AUTO_AI_HUMAN,
                            severity=Severity.MAJOR,
                            v0_value=" | ".join(c.text for c in r0),
                            v0_location=_table_loc(v0, t0, "v0", r0[0] if r0 else None),
                            confidence=0.90,
                            human_prompt="Vérifier que la suppression de cette ligne du tableau est justifiée.",
                            requires_human_action=True,
                        )
                    )

            for idx1, r1 in enumerate(rows1):
                if idx1 not in used_r1:
                    row_label = r1[0].text.strip() if r1 else "Ligne"
                    findings.append(
                        Finding(
                            finding_id=f"tdiff_{uuid.uuid4().hex[:10]}",
                            title=f"Ligne ajoutée dans '{label}' : '{row_label}'",
                            description=f"Nouvelle ligne présente en V1 p.{t1.page_number}.",
                            diff_category=DiffCategory.AJOUT,
                            control_type=ControlType.DIFF_V0_V1,
                            automation_level=AutomationLevel.AUTO_100,
                            severity=Severity.MINOR,
                            v1_value=" | ".join(c.text for c in r1),
                            v1_location=_table_loc(v1, t1, "v1", r1[0] if r1 else None),
                            confidence=0.90,
                        )
                    )

        return findings
