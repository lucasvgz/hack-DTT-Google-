"""100% Automatable deterministic checks (Controls 1 to 6 from reference taxonomy)."""

from __future__ import annotations

import re
import uuid
from difflib import SequenceMatcher

from urd_verifier.config import VerifierSettings
from urd_verifier.models.document import ParsedPDF, TableCell, TableData
from urd_verifier.models.findings import (
    AutomationLevel,
    ControlType,
    DiffCategory,
    Finding,
    Severity,
)
from .base import BaseCheckRunner, make_block_loc, make_page_loc, make_table_loc

_TOTAL_ROW_RE = re.compile(r"(?i)^(?:total|sous-total|somme)\b")
_TOTAL_COL_RE = re.compile(r"(?i)\b(?:total|somme)\b")
_VAR_COL_RE = re.compile(r"(?i)(?:var|évol|evol|%|variation|croissance)")
_YEAR_RE = re.compile(r"\b(20[12]\d)\b")
_PLACEHOLDER_RE = re.compile(r"(?i)\[?\b(?:à\s+compl[eé]ter|tbd|xx+|en\s+attente)\b\]?")
_IXBRL_TAG_RE = re.compile(r"<ix:nonFraction([^>]*)>(.*?)</ix:nonFraction>", re.IGNORECASE | re.DOTALL)


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


class DeterministicChecks(BaseCheckRunner):
    """Runs all 6 100%-automatable verification controls."""

    def __init__(self, settings: VerifierSettings) -> None:
        self.settings = settings

    def run(
        self,
        v0: ParsedPDF,
        v1: ParsedPDF,
        urd_n_minus_1: ParsedPDF | None = None,
    ) -> list[Finding]:
        findings: list[Finding] = []
        # Run core deterministic checks primarily on V1 (and attach V0 context if relevant)
        findings.extend(self._check_table_arithmetic(v1, role="v1"))
        findings.extend(self._check_variation_calculations(v1, role="v1"))
        findings.extend(self._check_cross_refs_and_concordance(v1, role="v1"))
        findings.extend(self._check_comparatif_n_minus_1(v0, v1, urd_n_minus_1))
        findings.extend(self._check_document_hygiene(v1, role="v1"))
        findings.extend(self._check_esef_compliance(v1, role="v1"))
        return findings

    # 1. Arithmétique des tableaux
    def _check_table_arithmetic(self, doc: ParsedPDF, role: str) -> list[Finding]:
        findings: list[Finding] = []
        tol = self.settings.arithmetic_tolerance

        for tbl in doc.tables:
            if len(tbl.rows) < 3:
                continue

            # Identify percentage/variation columns to exclude from vertical sums
            pct_cols = {
                c_idx
                for c_idx, h in enumerate(tbl.headers)
                if _VAR_COL_RE.search(h) or "%" in h
            }

            # Vertical sums: sum blocks of rows preceding each "Total" / "Sous-total" row
            last_total_row = 0  # row 0 is headers
            for r_idx in range(1, len(tbl.rows)):
                row = tbl.rows[r_idx]
                if not row:
                    continue
                row_label = row[0].text.strip()
                if not _TOTAL_ROW_RE.search(row_label):
                    continue

                is_grand_total = "général" in row_label.lower() or (
                    row_label.lower().startswith("total") and "sous" not in row_label.lower()
                )
                start_row = 1 if is_grand_total else last_total_row + 1
                # Exclude nested subtotal rows if grand total has subtotals inside
                candidate_rows = [
                    tbl.rows[k]
                    for k in range(start_row, r_idx)
                    if not (is_grand_total and _TOTAL_ROW_RE.search(tbl.rows[k][0].text.strip()))
                ]
                if not candidate_rows:
                    candidate_rows = tbl.rows[start_row:r_idx]

                if len(candidate_rows) >= 2:
                    for c_idx in range(1, len(row)):
                        if c_idx in pct_cols:
                            continue
                        total_cell = row[c_idx]
                        if total_cell.numeric_value is None or total_cell.is_percent:
                            continue

                        component_vals: list[float] = []
                        for cr in candidate_rows:
                            if c_idx < len(cr) and cr[c_idx].numeric_value is not None and not cr[c_idx].is_percent:
                                component_vals.append(cr[c_idx].numeric_value)

                        if len(component_vals) >= 2:
                            expected = round(sum(component_vals), 4)
                            actual = total_cell.numeric_value
                            diff = round(actual - expected, 4)
                            if abs(diff) > tol:
                                col_hdr = tbl.headers[c_idx] if c_idx < len(tbl.headers) else f"Col {c_idx}"
                                findings.append(
                                    Finding(
                                        finding_id=f"arith_{uuid.uuid4().hex[:10]}",
                                        title=f"Erreur d'addition verticale dans '{tbl.title or tbl.table_id}' ({row_label})",
                                        description=(
                                            f"Colonne '{col_hdr}', ligne '{row_label}' : valeur affichée = {actual}, "
                                            f"somme calculée = {expected} (écart = {diff:+.2f}, tolérance ±{tol})."
                                        ),
                                        diff_category=DiffCategory.CHIFFRAGE,
                                        control_type=ControlType.ARITHMETIQUE_TABLEAUX,
                                        automation_level=AutomationLevel.AUTO_100,
                                        severity=Severity.CRITICAL if abs(diff) > tol * 3 else Severity.MAJOR,
                                        v1_value=str(actual),
                                        expected_value=str(expected),
                                        numeric_delta=diff,
                                        v1_location=make_table_loc(doc, tbl, role, total_cell),
                                        confidence=0.97,
                                        ai_rationale=f"Somme des {len(component_vals)} composantes = {expected} != {actual}.",
                                    )
                                )
                last_total_row = r_idx

            # Horizontal sums: if a header is "Total", sum preceding numeric non-pct cols
            total_col_idxs = [
                c_idx for c_idx, h in enumerate(tbl.headers) if _TOTAL_COL_RE.search(h)
            ]
            if total_col_idxs:
                tc_idx = total_col_idxs[-1]
                sum_cols = [
                    c for c in range(1, tc_idx) if c not in pct_cols
                ]
                if len(sum_cols) >= 2:
                    for r_idx in range(1, len(tbl.rows)):
                        row = tbl.rows[r_idx]
                        if tc_idx >= len(row):
                            continue
                        tcell = row[tc_idx]
                        if tcell.numeric_value is None or tcell.is_percent:
                            continue
                        vals = [
                            row[c].numeric_value
                            for c in sum_cols
                            if c < len(row) and row[c].numeric_value is not None and not row[c].is_percent
                        ]
                        if len(vals) == len(sum_cols):
                            expected = round(sum(vals), 4)
                            actual = tcell.numeric_value
                            diff = round(actual - expected, 4)
                            if abs(diff) > tol:
                                findings.append(
                                    Finding(
                                        finding_id=f"arithh_{uuid.uuid4().hex[:10]}",
                                        title=f"Erreur d'addition horizontale dans '{tbl.title or tbl.table_id}' ({row[0].text})",
                                        description=(
                                            f"Ligne '{row[0].text}' : Total affiché = {actual}, somme horizontale = {expected} (écart = {diff:+.2f})."
                                        ),
                                        diff_category=DiffCategory.CHIFFRAGE,
                                        control_type=ControlType.ARITHMETIQUE_TABLEAUX,
                                        automation_level=AutomationLevel.AUTO_100,
                                        severity=Severity.CRITICAL if abs(diff) > tol * 3 else Severity.MAJOR,
                                        v1_value=str(actual),
                                        expected_value=str(expected),
                                        numeric_delta=diff,
                                        v1_location=make_table_loc(doc, tbl, role, tcell),
                                        confidence=0.96,
                                    )
                                )
        return findings

    # 2. Calculs de variations
    def _check_variation_calculations(self, doc: ParsedPDF, role: str) -> list[Finding]:
        findings: list[Finding] = []
        tol_pct = self.settings.variation_tolerance_pct

        for tbl in doc.tables:
            if len(tbl.headers) < 3 or len(tbl.rows) < 2:
                continue

            # Detect year columns and variation column
            year_cols: list[tuple[int, int]] = []  # (col_idx, year)
            var_cols: list[int] = []
            for c_idx, h in enumerate(tbl.headers):
                ym = _YEAR_RE.search(h)
                if ym and not _VAR_COL_RE.search(h):
                    year_cols.append((c_idx, int(ym.group(1))))
                elif _VAR_COL_RE.search(h):
                    var_cols.append(c_idx)

            if len(year_cols) < 2 or not var_cols:
                continue

            # Sort year_cols by year descending: latest is N, previous is N-1
            year_cols.sort(key=lambda x: x[1], reverse=True)
            col_n, year_n = year_cols[0]
            col_prev, year_prev = year_cols[1]
            col_var = var_cols[0]

            for r_idx in range(1, len(tbl.rows)):
                row = tbl.rows[r_idx]
                if max(col_n, col_prev, col_var) >= len(row):
                    continue
                val_n = row[col_n].numeric_value
                val_prev = row[col_prev].numeric_value
                val_var = row[col_var].numeric_value
                if val_n is None or val_prev is None or val_var is None or val_prev == 0:
                    continue

                expected_pct = round(((val_n - val_prev) / abs(val_prev)) * 100.0, 2)
                diff = round(val_var - expected_pct, 2)
                sign_inverted = (expected_pct * val_var < 0) and abs(expected_pct) > 0.2

                if abs(diff) > tol_pct or sign_inverted:
                    row_label = row[0].text.strip()
                    findings.append(
                        Finding(
                            finding_id=f"var_{uuid.uuid4().hex[:10]}",
                            title=(
                                f"Signe inversé sur variation '{row_label}' ({tbl.title or tbl.table_id})"
                                if sign_inverted
                                else f"Erreur de calcul de variation '{row_label}' ({tbl.title or tbl.table_id})"
                            ),
                            description=(
                                f"Variation {year_n} vs {year_prev} : affiché {val_var:+.2f} %, "
                                f"recalculé ({val_n} - {val_prev}) / |{val_prev}| = {expected_pct:+.2f} % "
                                f"(écart {diff:+.2f} pts)."
                            ),
                            diff_category=DiffCategory.CHIFFRAGE,
                            control_type=ControlType.CALCULS_VARIATIONS,
                            automation_level=AutomationLevel.AUTO_100,
                            severity=Severity.CRITICAL if sign_inverted else Severity.MAJOR,
                            v1_value=f"{val_var:+.2f} %",
                            expected_value=f"{expected_pct:+.2f} %",
                            numeric_delta=diff,
                            v1_location=make_table_loc(doc, tbl, role, row[col_var]),
                            confidence=0.98,
                            ai_rationale="Recalcul déterministe ligne par ligne de (N - N-1) / |N-1|.",
                        )
                    )
        return findings

    # 3. Renvois & tables de concordance
    def _check_cross_refs_and_concordance(self, doc: ParsedPDF, role: str) -> list[Finding]:
        findings: list[Finding] = []
        all_text_lower = "\n".join(p.raw_text.lower() for p in doc.pages)

        # Collect existing notes, sections, annexes, tables
        existing_notes: set[str] = set()
        for sec in doc.sections:
            m = re.search(r"(?i)\bnote\s+(\d+(?:\.\d+)?)\b", sec.title)
            if m:
                existing_notes.add(m.group(1))
        for m in re.finditer(r"(?im)^\s*note\s+(\d+(?:\.\d+)?)\s*[:\-–]", all_text_lower):
            existing_notes.add(m.group(1))

        for ref in doc.cross_refs:
            if ref.ref_type == "note":
                if ref.target_identifier not in existing_notes:
                    findings.append(
                        Finding(
                            finding_id=f"ref_{uuid.uuid4().hex[:10]}",
                            title=f"Renvoi cassé : '{ref.raw_text}' introuvable (p.{ref.page_number})",
                            description=(
                                f"La référence '{ref.raw_text}' (page {ref.page_number}) pointe vers la Note {ref.target_identifier}, "
                                f"qui n'existe pas dans le document (notes détectées : {sorted(existing_notes) or 'aucune'})."
                            ),
                            diff_category=DiffCategory.REGLEMENTAIRE_ESEF,
                            control_type=ControlType.RENVOIS_CONCORDANCE,
                            automation_level=AutomationLevel.AUTO_100,
                            severity=Severity.MAJOR,
                            v1_value=ref.raw_text,
                            expected_value="Note existante",
                            v1_location=make_page_loc(doc, ref.page_number, ref.bbox, role, ref.raw_text),
                            confidence=0.94,
                        )
                    )
            elif ref.ref_type == "page":
                try:
                    target_pg = int(ref.target_identifier)
                except ValueError:
                    continue
                if target_pg < 1 or target_pg > doc.page_count:
                    findings.append(
                        Finding(
                            finding_id=f"ref_{uuid.uuid4().hex[:10]}",
                            title=f"Renvoi de page hors bornes : '{ref.raw_text}' (p.{ref.page_number})",
                            description=f"Renvoi vers page {target_pg}, alors que le document contient {doc.page_count} pages.",
                            diff_category=DiffCategory.REGLEMENTAIRE_ESEF,
                            control_type=ControlType.RENVOIS_CONCORDANCE,
                            automation_level=AutomationLevel.AUTO_100,
                            severity=Severity.MAJOR,
                            v1_value=f"page {target_pg}",
                            expected_value=f"1..{doc.page_count}",
                            v1_location=make_page_loc(doc, ref.page_number, ref.bbox, role, ref.raw_text),
                            confidence=0.98,
                        )
                    )

        # Verify AMF Concordance table entries
        for entry in doc.concordance_entries:
            keywords = [
                w for w in re.findall(r"[a-zàâäéèêëïîôöùûüç]{4,}", entry.label.lower())
                if w not in {"table", "concordance", "informations", "annexe", "section", "chapitre"}
            ]
            for decl_pg in entry.declared_pages:
                if decl_pg < 1 or decl_pg > doc.page_count:
                    findings.append(
                        Finding(
                            finding_id=f"conc_{uuid.uuid4().hex[:10]}",
                            title=f"Table de concordance : page {decl_pg} inexistante pour '{entry.label}'",
                            description=f"La table de concordance renvoie à la page {decl_pg} (> {doc.page_count} pages).",
                            diff_category=DiffCategory.REGLEMENTAIRE_ESEF,
                            control_type=ControlType.RENVOIS_CONCORDANCE,
                            automation_level=AutomationLevel.AUTO_100,
                            severity=Severity.CRITICAL,
                            v1_value=f"p.{decl_pg}",
                            expected_value=f"<= p.{doc.page_count}",
                            v1_location=make_page_loc(doc, entry.page_number, entry.bbox, role, entry.label),
                            confidence=0.97,
                        )
                    )
                elif keywords:
                    target_text = doc.pages[decl_pg - 1].raw_text.lower()
                    hits = sum(1 for kw in keywords if kw in target_text)
                    if hits == 0:
                        findings.append(
                            Finding(
                                finding_id=f"conc_{uuid.uuid4().hex[:10]}",
                                title=f"Mauvais numéro de page AMF : '{entry.label}' -> p.{decl_pg}",
                                description=(
                                    f"La table de concordance indique la page {decl_pg} pour '{entry.label}', "
                                    f"mais aucun mot-clé ({', '.join(keywords[:4])}) n'apparaît sur cette page."
                                ),
                                diff_category=DiffCategory.REGLEMENTAIRE_ESEF,
                                control_type=ControlType.RENVOIS_CONCORDANCE,
                                automation_level=AutomationLevel.AUTO_100,
                                severity=Severity.MAJOR,
                                v1_value=f"p.{decl_pg}",
                                v1_location=make_page_loc(doc, entry.page_number, entry.bbox, role, entry.label),
                                confidence=0.88,
                                ai_rationale="Vérification lexicale entre l'entrée de la table de concordance AMF et le contenu de la page cible.",
                            )
                        )
        return findings

    # 4. Comparatif N-1 brut
    def _check_comparatif_n_minus_1(
        self,
        v0: ParsedPDF,
        v1: ParsedPDF,
        urd_n_minus_1: ParsedPDF | None,
    ) -> list[Finding]:
        findings: list[Finding] = []
        if urd_n_minus_1 is None:
            return findings

        # Compare N-1 column in V1 tables against published N column in URD N-1 tables
        for tbl1 in v1.tables:
            # Find N-1 year column in V1
            year_cols_1 = [
                (idx, int(_YEAR_RE.search(h).group(1)))
                for idx, h in enumerate(tbl1.headers)
                if _YEAR_RE.search(h) and not _VAR_COL_RE.search(h)
            ]
            if len(year_cols_1) < 2:
                continue
            year_cols_1.sort(key=lambda x: x[1])
            col_prev_1, target_year = year_cols_1[0]  # Oldest year column = N-1

            # Find matching table in URD N-1 containing column for target_year
            v1_row_labels = {_norm(r[0].text) for r in tbl1.rows[1:] if r and r[0].text.strip()}
            for tbl_old in urd_n_minus_1.tables:
                old_row_labels = {_norm(r[0].text) for r in tbl_old.rows[1:] if r and r[0].text.strip()}
                shared_rows = len(v1_row_labels & old_row_labels)
                title_sim = SequenceMatcher(None, _norm(tbl1.title), _norm(tbl_old.title)).ratio()
                if title_sim < 0.55 and shared_rows < 2:
                    continue
                old_col = next(
                    (
                        idx
                        for idx, h in enumerate(tbl_old.headers)
                        if str(target_year) in h and not _VAR_COL_RE.search(h)
                    ),
                    None,
                )
                if old_col is None:
                    continue

                # Match rows by label
                for r1 in tbl1.rows[1:]:
                    if col_prev_1 >= len(r1) or r1[col_prev_1].numeric_value is None:
                        continue
                    lbl1 = _norm(r1[0].text)
                    for r_old in tbl_old.rows[1:]:
                        if old_col >= len(r_old) or r_old[old_col].numeric_value is None:
                            continue
                        if SequenceMatcher(None, lbl1, _norm(r_old[0].text)).ratio() >= 0.80:
                            val_curr_n1 = r1[col_prev_1].numeric_value
                            val_pub_n1 = r_old[old_col].numeric_value
                            if abs(val_curr_n1 - val_pub_n1) > 0.01:
                                delta = round(val_curr_n1 - val_pub_n1, 4)
                                findings.append(
                                    Finding(
                                        finding_id=f"compn1_{uuid.uuid4().hex[:10]}",
                                        title=f"Écart comparatif N-1 brut ({target_year}) : {r1[0].text}",
                                        description=(
                                            f"Dans '{tbl1.title or tbl1.table_id}', le chiffre {target_year} en V1 ({val_curr_n1}) "
                                            f"diffère de celui publié dans l'URD {target_year} ({val_pub_n1}, delta {delta:+.2f})."
                                        ),
                                        diff_category=DiffCategory.CHIFFRAGE,
                                        control_type=ControlType.COMPARATIF_N_1_BRUT,
                                        automation_level=AutomationLevel.AUTO_100,
                                        severity=Severity.CRITICAL,
                                        v1_value=str(val_curr_n1),
                                        expected_value=str(val_pub_n1),
                                        numeric_delta=delta,
                                        v1_location=make_table_loc(v1, tbl1, "v1", r1[col_prev_1]),
                                        extra_locations=[
                                            make_table_loc(urd_n_minus_1, tbl_old, "urd_n_minus_1", r_old[old_col])
                                        ],
                                        confidence=0.95,
                                        human_prompt="Vérifier si cet écart N-1 brut correspond à un retraitement justifié (IFRS 5 / changement de méthode) ou à une erreur.",
                                        requires_human_action=True,
                                    )
                                )
                            break
                break
        return findings

    # 5. Hygiène documentaire
    def _check_document_hygiene(self, doc: ParsedPDF, role: str) -> list[Finding]:
        findings: list[Finding] = []

        # Track dominant year column ordering (descending e.g. 2025 | 2024 vs ascending 2024 | 2025)
        orders: list[tuple[TableData, str]] = []
        for tbl in doc.tables:
            years = [
                (idx, int(_YEAR_RE.search(h).group(1)))
                for idx, h in enumerate(tbl.headers)
                if _YEAR_RE.search(h) and not _VAR_COL_RE.search(h)
            ]
            if len(years) >= 2:
                order = "desc" if years[0][1] > years[1][1] else "asc"
                orders.append((tbl, order))
            elif len(years) == 1 and len([c for c in tbl.rows[1][1:] if c.numeric_value is not None]) >= 2 if len(tbl.rows) > 1 else False:
                # Missing N-1 year in column headers despite multiple numeric columns
                findings.append(
                    Finding(
                        finding_id=f"hyg_{uuid.uuid4().hex[:10]}",
                        title=f"Année N-1 manquante dans les en-têtes de '{tbl.title or tbl.table_id}'",
                        description=f"Le tableau comporte plusieurs colonnes numériques mais une seule année ({years[0][1]}) dans les en-têtes : {tbl.headers}.",
                        diff_category=DiffCategory.METADONNEES,
                        control_type=ControlType.HYGIENE_DOCUMENTAIRE,
                        automation_level=AutomationLevel.AUTO_100,
                        severity=Severity.MAJOR,
                        v1_value=" | ".join(tbl.headers),
                        v1_location=make_table_loc(doc, tbl, role),
                        confidence=0.90,
                    )
                )

        if len(orders) >= 2:
            desc_count = sum(1 for _, o in orders if o == "desc")
            asc_count = len(orders) - desc_count
            if desc_count > 0 and asc_count > 0:
                minority_order = "asc" if desc_count >= asc_count else "desc"
                for tbl, order in orders:
                    if order == minority_order:
                        findings.append(
                            Finding(
                                finding_id=f"hyg_{uuid.uuid4().hex[:10]}",
                                title=f"Colonnes N / N-1 inversées dans '{tbl.title or tbl.table_id}'",
                                description=(
                                    f"Ordre des colonnes ({tbl.headers}) opposé à la convention majoritaire du document "
                                    f"({'N | N-1' if minority_order == 'asc' else 'N-1 | N'})."
                                ),
                                diff_category=DiffCategory.METADONNEES,
                                control_type=ControlType.HYGIENE_DOCUMENTAIRE,
                                automation_level=AutomationLevel.AUTO_100,
                                severity=Severity.CRITICAL,
                                v1_value=" | ".join(tbl.headers),
                                v1_location=make_table_loc(doc, tbl, role),
                                confidence=0.93,
                            )
                        )

        # Check placeholders ([À compléter], TBD, XX) & page numbering mismatches
        for page in doc.pages:
            if (
                page.displayed_page_number is not None
                and page.displayed_page_number != page.page_number
            ):
                footer_blk = next(
                    (b for b in page.blocks if b.block_type in {"footer", "header"}),
                    page.blocks[-1] if page.blocks else None,
                )
                if footer_blk:
                    findings.append(
                        Finding(
                            finding_id=f"hyg_{uuid.uuid4().hex[:10]}",
                            title=f"Numérotation de page incohérente (PDF p.{page.page_number} affiche p.{page.displayed_page_number})",
                            description=(
                                f"La page physique {page.page_number} du PDF affiche le numéro {page.displayed_page_number} en pied/en-tête."
                            ),
                            diff_category=DiffCategory.METADONNEES,
                            control_type=ControlType.HYGIENE_DOCUMENTAIRE,
                            automation_level=AutomationLevel.AUTO_100,
                            severity=Severity.MINOR,
                            v1_value=str(page.displayed_page_number),
                            expected_value=str(page.page_number),
                            v1_location=make_block_loc(doc, footer_blk, role),
                            confidence=0.92,
                        )
                    )

            for blk in page.blocks:
                m = _PLACEHOLDER_RE.search(blk.text)
                if m:
                    findings.append(
                        Finding(
                            finding_id=f"hyg_{uuid.uuid4().hex[:10]}",
                            title=f"Mention provisoire non finalisée '{m.group(0)}' (p.{page.page_number})",
                            description=f"Marqueur provisoire détecté dans V1 : « {blk.text[:160]} »",
                            diff_category=DiffCategory.METADONNEES,
                            control_type=ControlType.HYGIENE_DOCUMENTAIRE,
                            automation_level=AutomationLevel.AUTO_100,
                            severity=Severity.CRITICAL,
                            v1_value=m.group(0),
                            v1_location=make_block_loc(doc, blk, role),
                            confidence=0.98,
                        )
                    )

        return findings

    # 6. Conformité technique ESEF
    def _check_esef_compliance(self, doc: ParsedPDF, role: str) -> list[Finding]:
        findings: list[Finding] = []
        full_text = "\n".join(p.raw_text for p in doc.pages)

        # Check explicit iXBRL snippet validation if embedded in document
        for page in doc.pages:
            for blk in page.blocks:
                for m in _IXBRL_TAG_RE.finditer(blk.text):
                    attrs, inner = m.group(1), m.group(2).strip()
                    has_neg_sign = 'sign="-"' in attrs or "sign='-'" in attrs
                    looks_negative = inner.startswith(("(", "-", "−"))
                    if looks_negative and not has_neg_sign:
                        findings.append(
                            Finding(
                                finding_id=f"esef_{uuid.uuid4().hex[:10]}",
                                title=f"Signe négatif iXBRL mal balisé (p.{page.page_number})",
                                description=(
                                    f"Balise ix:nonFraction avec valeur négative '{inner}' sans attribut sign=\"-\"."
                                ),
                                diff_category=DiffCategory.REGLEMENTAIRE_ESEF,
                                control_type=ControlType.CONFORMITE_ESEF,
                                automation_level=AutomationLevel.AUTO_100,
                                severity=Severity.CRITICAL,
                                v1_value=m.group(0),
                                expected_value='Attribut sign="-" requis',
                                v1_location=make_block_loc(doc, blk, role),
                                confidence=0.99,
                            )
                        )
                # Also detect explicit ESEF warnings/errors in text (e.g. missing tag / untagged)
                if re.search(r"(?i)\b(?:tag\s+ixbrl\s+manquant|non\s+balis[eé]\s+esef|erreur\s+esma)\b", blk.text):
                    findings.append(
                        Finding(
                            finding_id=f"esef_{uuid.uuid4().hex[:10]}",
                            title=f"Anomalie ESEF / iXBRL signalée (p.{page.page_number})",
                            description=blk.text[:240],
                            diff_category=DiffCategory.REGLEMENTAIRE_ESEF,
                            control_type=ControlType.CONFORMITE_ESEF,
                            automation_level=AutomationLevel.AUTO_100,
                            severity=Severity.MAJOR,
                            v1_value=blk.text[:240],
                            v1_location=make_block_loc(doc, blk, role),
                            confidence=0.90,
                        )
                    )

        # Check if financial statements exist without any ESEF mention across the URD
        has_financial_statements = bool(
            re.search(r"(?i)\b(compte\s+de\s+r[eé]sultat|bilan\s+consolid[eé]|états\s+financiers)\b", full_text)
        )
        if has_financial_statements and not doc.esef_signals:
            first_page = doc.pages[0]
            if first_page.blocks:
                findings.append(
                    Finding(
                        finding_id=f"esef_{uuid.uuid4().hex[:10]}",
                        title="Aucune mention de conformité ESEF / balisage iXBRL détectée",
                        description=(
                            "Le document contient des états financiers consolidés mais aucune mention ESEF / iXBRL "
                            "(RTS ESMA) n'a été trouvée dans le PDF (vérifier le package XHTML/iXBRL associé)."
                        ),
                        diff_category=DiffCategory.REGLEMENTAIRE_ESEF,
                        control_type=ControlType.CONFORMITE_ESEF,
                        automation_level=AutomationLevel.AUTO_100,
                        severity=Severity.MINOR,
                        v1_location=make_block_loc(doc, first_page.blocks[0], role),
                        confidence=0.85,
                    )
                )

        return findings
