"""Semi-automatic AI + Human checks (Controls 7 to 11 from reference taxonomy)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from urd_verifier.agent.llm_client import LLMClient
from urd_verifier.config import VerifierSettings
from urd_verifier.ingestion.number_parser import (
    detect_unit_in_text,
    extract_numbers_from_text,
    parse_financial_number,
)
from urd_verifier.models.document import ParsedPDF, TableData, TextBlock
from urd_verifier.models.findings import (
    AutomationLevel,
    ControlType,
    DiffCategory,
    Finding,
    LocationRef,
    Severity,
)
from .base import BaseCheckRunner, make_block_loc, make_page_loc, make_table_loc

_KPI_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("chiffre_affaires", re.compile(r"(?i)\b(chiffre\s+d['’]affaires|ca\s+consolid[eé]|revenus?)\b")),
    ("ebitda", re.compile(r"(?i)\b(ebitda(?:\s+ajust[eé])?|exc[eé]dent\s+brut\s+d['’]exploitation|ebe)\b")),
    ("resultat_net", re.compile(r"(?i)\b(r[eé]sultat\s+net(?:\s+part\s+du\s+groupe)?)\b")),
    ("dette_nette", re.compile(r"(?i)\b(dette\s+nette|endettement\s+net)\b")),
    ("capex", re.compile(r"(?i)\b(capex|investissements?\s+(?:totaux|industriels|corporels))\b")),
    ("effectifs", re.compile(r"(?i)\b(effectifs?\s+(?:moyens|totaux|etp|salari[eé]s)?)\b")),
]

_CSRD_SECTION_RE = re.compile(
    r"(?i)\b(csrd|durabilit[eé]|esg|taxonomie|esrs|environnement|social)\b"
)


@dataclass
class _KPIObservation:
    kpi_key: str
    kpi_label: str
    value: float
    unit: str | None
    is_percent: bool
    section_title: str
    source_kind: str  # "table" | "narrative"
    location: LocationRef
    snippet: str


def _to_base_eur(value: float, unit: str | None) -> float:
    if unit == "Md€":
        return value * 1_000_000_000.0
    if unit == "M€":
        return value * 1_000_000.0
    if unit == "k€":
        return value * 1_000.0
    return value


class AISemanticChecks(BaseCheckRunner):
    """Runs controls 7-11 using AI/Vision when available + deterministic NLP/cross-check heuristics."""

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
        observations = self._collect_kpi_observations(v1, role="v1")

        # 7. Cross-checks inter-sections
        findings.extend(self._check_cross_section_kpis(observations))
        # 8. Cohérence texte vs tableau
        findings.extend(self._check_narrative_vs_table(v1, observations, role="v1"))
        # 9. Unités & échelles
        findings.extend(self._check_units_and_scales(v1, observations, role="v1"))
        # 10. Graphiques vs tableaux (Vision LLM + vector label fallback)
        findings.extend(self._check_charts_vs_tables(v1, role="v1"))
        # 11. Lien Finance / Durabilité (CSRD)
        findings.extend(self._check_finance_vs_csrd(v1, observations, role="v1"))

        # Optional LLM semantic pass on V0 vs V1 narrative contradictions
        if self.llm.is_online:
            findings.extend(self._llm_cross_check_pass(v0, v1))

        return findings

    def _collect_kpi_observations(
        self, doc: ParsedPDF, role: str
    ) -> list[_KPIObservation]:
        obs: list[_KPIObservation] = []

        # From tables (focus on latest year column or first numeric column)
        for tbl in doc.tables:
            # Find latest year column index
            year_cols: list[tuple[int, int]] = []
            for idx, h in enumerate(tbl.headers):
                ym = re.search(r"\b(20[12]\d)\b", h)
                if ym and "%" not in h and "var" not in h.lower():
                    year_cols.append((idx, int(ym.group(1))))
            year_cols.sort(key=lambda x: x[1], reverse=True)
            target_col = year_cols[0][0] if year_cols else 1

            for row in tbl.rows[1:]:
                if not row or target_col >= len(row):
                    continue
                lbl = row[0].text.strip()
                for kpi_key, pat in _KPI_PATTERNS:
                    if pat.search(lbl):
                        cell = row[target_col]
                        if cell.numeric_value is not None and not cell.is_percent:
                            unit = cell.unit_hint or tbl.unit_hint or None
                            obs.append(
                                _KPIObservation(
                                    kpi_key=kpi_key,
                                    kpi_label=lbl,
                                    value=cell.numeric_value,
                                    unit=unit,
                                    is_percent=False,
                                    section_title=tbl.section_title or f"Page {tbl.page_number}",
                                    source_kind="table",
                                    location=make_table_loc(doc, tbl, role, cell),
                                    snippet=f"{lbl}: {cell.text} ({unit or ''})",
                                )
                            )
                        # Also capture % variation on the same row if present
                        for c_idx, h in enumerate(tbl.headers):
                            if ("%" in h or "var" in h.lower() or "évol" in h.lower()) and c_idx < len(row):
                                vc = row[c_idx]
                                if vc.numeric_value is not None:
                                    obs.append(
                                        _KPIObservation(
                                            kpi_key=f"{kpi_key}_var",
                                            kpi_label=f"{lbl} (variation)",
                                            value=vc.numeric_value,
                                            unit="%",
                                            is_percent=True,
                                            section_title=tbl.section_title or f"Page {tbl.page_number}",
                                            source_kind="table",
                                            location=make_table_loc(doc, tbl, role, vc),
                                            snippet=f"{lbl} var: {vc.text}",
                                        )
                                    )

        # From narrative text blocks (sentence by sentence)
        for page in doc.pages:
            for blk in page.blocks:
                if blk.block_type in {"header", "footer", "heading"}:
                    continue
                for sent in re.split(r"(?<=[.!?])\s+", blk.text.replace("\n", " ")):
                    for kpi_key, pat in _KPI_PATTERNS:
                        if not pat.search(sent):
                            continue
                        nums = extract_numbers_from_text(sent)
                        if not nums:
                            continue
                        for n in nums:
                            if n.is_percent:
                                obs.append(
                                    _KPIObservation(
                                        kpi_key=f"{kpi_key}_var",
                                        kpi_label=kpi_key,
                                        value=n.value,
                                        unit="%",
                                        is_percent=True,
                                        section_title=blk.section_title or f"Page {page.page_number}",
                                        source_kind="narrative",
                                        location=make_block_loc(doc, blk, role),
                                        snippet=sent[:240],
                                    )
                                )
                            else:
                                unit = n.unit
                                if unit is None:
                                    u, _ = detect_unit_in_text(sent)
                                    unit = u
                                obs.append(
                                    _KPIObservation(
                                        kpi_key=kpi_key,
                                        kpi_label=kpi_key,
                                        value=n.value,
                                        unit=unit,
                                        is_percent=False,
                                        section_title=blk.section_title or f"Page {page.page_number}",
                                        source_kind="narrative",
                                        location=make_block_loc(doc, blk, role),
                                        snippet=sent[:240],
                                    )
                                )
                        break
        return obs

    # 7. Cross-checks inter-sections
    def _check_cross_section_kpis(self, obs: list[_KPIObservation]) -> list[Finding]:
        findings: list[Finding] = []
        by_kpi: dict[str, list[_KPIObservation]] = {}
        for o in obs:
            if o.is_percent:
                continue
            by_kpi.setdefault(o.kpi_key, []).append(o)

        seen_pairs: set[tuple[str, int, int]] = set()
        for kpi_key, items in by_kpi.items():
            table_items = [i for i in items if i.source_kind == "table"]
            if len(table_items) < 2:
                continue
            ref = table_items[0]
            for other in table_items[1:]:
                if other.location.page_number == ref.location.page_number and other.location.table_id == ref.location.table_id:
                    continue
                pair_sig = (
                    kpi_key,
                    min(ref.location.page_number, other.location.page_number),
                    max(ref.location.page_number, other.location.page_number),
                )
                if pair_sig in seen_pairs:
                    continue

                # Compare normalized EUR values if both have units, else raw if same unit
                v_ref = _to_base_eur(ref.value, ref.unit) if (ref.unit and other.unit) else ref.value
                v_oth = _to_base_eur(other.value, other.unit) if (ref.unit and other.unit) else other.value

                # Avoid double-reporting pure 1000x unit mismatch (handled in check 9)
                if v_ref != 0 and abs(abs(v_oth / v_ref) - 1000.0) < 5.0 and ref.unit != other.unit:
                    continue

                if abs(v_ref - v_oth) > 0.5:
                    seen_pairs.add(pair_sig)
                    findings.append(
                        Finding(
                            finding_id=f"xsec_{uuid.uuid4().hex[:10]}",
                            title=f"Incohérence inter-sections sur '{ref.kpi_label}'",
                            description=(
                                f"Valeur différente entre '{ref.section_title}' (p.{ref.location.page_number} : {ref.value} {ref.unit or ''}) "
                                f"et '{other.section_title}' (p.{other.location.page_number} : {other.value} {other.unit or ''})."
                            ),
                            diff_category=DiffCategory.CHIFFRAGE,
                            control_type=ControlType.CROSS_CHECKS_INTER_SECTIONS,
                            automation_level=AutomationLevel.SEMI_AUTO_AI_HUMAN,
                            severity=Severity.MAJOR,
                            v0_value=f"{ref.value} {ref.unit or ''} (p.{ref.location.page_number})",
                            v1_value=f"{other.value} {other.unit or ''} (p.{other.location.page_number})",
                            numeric_delta=round(other.value - ref.value, 2),
                            v1_location=other.location,
                            extra_locations=[ref.location],
                            confidence=0.86,
                            ai_rationale="Rapprochement automatique d'un indicateur clé cité dans plusieurs sections du document.",
                            human_prompt="Vérifier si le périmètre diffère entre les deux sections (ex. agrégat ajusté vs publié, ou périmètre IFRS 5).",
                            requires_human_action=True,
                        )
                    )
        return findings

    # 8. Cohérence texte vs tableau
    def _check_narrative_vs_table(
        self, doc: ParsedPDF, obs: list[_KPIObservation], role: str
    ) -> list[Finding]:
        findings: list[Finding] = []
        table_obs = [o for o in obs if o.source_kind == "table"]
        narr_obs = [o for o in obs if o.source_kind == "narrative"]

        seen: set[tuple[str, int, float]] = set()
        for no in narr_obs:
            matching_tbls = [t for t in table_obs if t.kpi_key == no.kpi_key]
            if not matching_tbls:
                continue
            # Pick closest table by page number
            best_tbl = min(
                matching_tbls,
                key=lambda t: abs(t.location.page_number - no.location.page_number),
            )
            if no.is_percent:
                if abs(no.value - best_tbl.value) > 0.15:
                    sig = (no.kpi_key, no.location.page_number, no.value)
                    if sig in seen:
                        continue
                    seen.add(sig)
                    findings.append(
                        Finding(
                            finding_id=f"txt_tbl_{uuid.uuid4().hex[:10]}",
                            title=f"Écart texte vs tableau ({no.kpi_label}) : {no.value:+.2f} % vs {best_tbl.value:+.2f} %",
                            description=(
                                f"Le texte (p.{no.location.page_number}) annonce {no.value:+.2f} % (« {no.snippet} »), "
                                f"alors que le tableau (p.{best_tbl.location.page_number}) affiche {best_tbl.value:+.2f} %."
                            ),
                            diff_category=DiffCategory.CHIFFRAGE,
                            control_type=ControlType.COHERENCE_TEXTE_TABLEAU,
                            automation_level=AutomationLevel.SEMI_AUTO_AI_HUMAN,
                            severity=Severity.MAJOR,
                            v0_value=f"Tableau p.{best_tbl.location.page_number} : {best_tbl.value:+.2f} %",
                            v1_value=f"Texte p.{no.location.page_number} : {no.value:+.2f} %",
                            numeric_delta=round(no.value - best_tbl.value, 2),
                            v1_location=no.location,
                            extra_locations=[best_tbl.location],
                            confidence=0.88,
                            ai_rationale="Comparaison des taux d'évolution mentionnés dans le narratif par rapport aux tableaux chiffrés.",
                            human_prompt="Vérifier s'il s'agit d'une croissance organique/à taux de change constants vs publiée, ou d'une erreur rédactionnelle.",
                            requires_human_action=True,
                        )
                    )
            else:
                v_n = _to_base_eur(no.value, no.unit) if (no.unit and best_tbl.unit) else no.value
                v_t = _to_base_eur(best_tbl.value, best_tbl.unit) if (no.unit and best_tbl.unit) else best_tbl.value
                if v_t != 0 and abs(v_n - v_t) / abs(v_t) > 0.005:
                    # Skip 1000x unit mismatch handled in check 9
                    if abs(abs(v_n / v_t) - 1000.0) < 10.0:
                        continue
                    sig = (no.kpi_key, no.location.page_number, no.value)
                    if sig in seen:
                        continue
                    seen.add(sig)
                    findings.append(
                        Finding(
                            finding_id=f"txt_tbl_{uuid.uuid4().hex[:10]}",
                            title=f"Incohérence texte vs tableau sur {no.kpi_label}",
                            description=(
                                f"Le narratif (p.{no.location.page_number}) indique {no.value} {no.unit or ''}, "
                                f"tandis que le tableau (p.{best_tbl.location.page_number}) indique {best_tbl.value} {best_tbl.unit or ''}."
                            ),
                            diff_category=DiffCategory.CHIFFRAGE,
                            control_type=ControlType.COHERENCE_TEXTE_TABLEAU,
                            automation_level=AutomationLevel.SEMI_AUTO_AI_HUMAN,
                            severity=Severity.MAJOR,
                            v0_value=f"Tableau : {best_tbl.value} {best_tbl.unit or ''}",
                            v1_value=f"Texte : {no.value} {no.unit or ''}",
                            numeric_delta=round(no.value - best_tbl.value, 2),
                            v1_location=no.location,
                            extra_locations=[best_tbl.location],
                            confidence=0.85,
                            human_prompt="Confirmer si les deux chiffres portent sur le même périmètre comptable.",
                            requires_human_action=True,
                        )
                    )
        return findings

    # 9. Unités & échelles (k€ / M€ / Md€)
    def _check_units_and_scales(
        self, doc: ParsedPDF, obs: list[_KPIObservation], role: str
    ) -> list[Finding]:
        findings: list[Finding] = []

        # A. Check title vs headers/cells unit conflict within the same table
        for tbl in doc.tables:
            title_unit, _ = detect_unit_in_text(tbl.title)
            hdr_unit, _ = detect_unit_in_text(" ".join(tbl.headers))
            if title_unit and hdr_unit and title_unit != hdr_unit:
                findings.append(
                    Finding(
                        finding_id=f"unit_{uuid.uuid4().hex[:10]}",
                        title=f"Confusion d'unité dans '{tbl.title or tbl.table_id}' ({title_unit} vs {hdr_unit})",
                        description=(
                            f"Le titre du tableau mentionne '{title_unit}' alors que les en-têtes indiquent '{hdr_unit}'."
                        ),
                        diff_category=DiffCategory.CHIFFRAGE,
                        control_type=ControlType.UNITES_ECHELLES,
                        automation_level=AutomationLevel.SEMI_AUTO_AI_HUMAN,
                        severity=Severity.CRITICAL,
                        v1_value=f"Titre={title_unit}, En-tête={hdr_unit}",
                        v1_location=make_table_loc(doc, tbl, role),
                        confidence=0.95,
                        human_prompt="Confirmer la bonne unité (k€ / M€ / Md€) et vérifier l'ordre de grandeur des montants du tableau.",
                        requires_human_action=True,
                    )
                )

        # B. Check 1000x magnitude mismatch on same KPI (e.g. 1 200 k€ vs 1 200 M€)
        by_kpi: dict[str, list[_KPIObservation]] = {}
        for o in obs:
            if not o.is_percent and o.unit in {"k€", "M€", "Md€"}:
                by_kpi.setdefault(o.kpi_key, []).append(o)

        for kpi_key, items in by_kpi.items():
            if len(items) < 2:
                continue
            ref = items[0]
            for other in items[1:]:
                if ref.unit == other.unit:
                    continue
                ratio = (other.value / ref.value) if ref.value else 0.0
                base_ratio = _to_base_eur(other.value, other.unit) / _to_base_eur(ref.value, ref.unit) if ref.value else 0.0
                # If raw numbers are nearly identical (e.g. both say "1 250") but units differ (k€ vs M€) -> huge bug!
                if 0.9 <= ratio <= 1.1 and (base_ratio >= 500 or base_ratio <= 0.002):
                    findings.append(
                        Finding(
                            finding_id=f"unit_{uuid.uuid4().hex[:10]}",
                            title=f"Confusion d'échelle ({ref.unit} vs {other.unit}) sur '{kpi_key}'",
                            description=(
                                f"Même valeur brute (~{ref.value}) exprimée en '{ref.unit}' (p.{ref.location.page_number}) "
                                f"et en '{other.unit}' (p.{other.location.page_number}) — écart d'un facteur {max(base_ratio, 1/base_ratio):.0f}x."
                            ),
                            diff_category=DiffCategory.CHIFFRAGE,
                            control_type=ControlType.UNITES_ECHELLES,
                            automation_level=AutomationLevel.SEMI_AUTO_AI_HUMAN,
                            severity=Severity.CRITICAL,
                            v0_value=f"{ref.value} {ref.unit} (p.{ref.location.page_number})",
                            v1_value=f"{other.value} {other.unit} (p.{other.location.page_number})",
                            v1_location=other.location,
                            extra_locations=[ref.location],
                            confidence=0.94,
                            human_prompt="Confirmer l'échelle exacte (k€ / M€ / Md€) et corriger l'unité erronée.",
                            requires_human_action=True,
                        )
                    )
                    break
        return findings

    # 10. Graphiques vs tableaux
    def _check_charts_vs_tables(self, doc: ParsedPDF, role: str) -> list[Finding]:
        findings: list[Finding] = []
        if not doc.charts:
            return findings

        for chart in doc.charts:
            # Find candidate tables near or related to chart title
            chart_words = set(re.findall(r"[a-zàâäéèêëïîôöùûüç]{4,}", chart.title.lower()))
            related_tables = sorted(
                [
                    t
                    for t in doc.tables
                    if abs(t.page_number - chart.page_number) <= 2
                    or len(chart_words & set(re.findall(r"[a-zàâäéèêëïîôöùûüç]{4,}", t.title.lower()))) >= 2
                ],
                key=lambda t: (
                    -len(chart_words & set(re.findall(r"[a-zàâäéèêëïîôöùûüç]{4,}", t.title.lower()))),
                    abs(t.page_number - chart.page_number),
                ),
            )
            if not related_tables:
                continue
            tbl = related_tables[0]

            # 1. Vision LLM pass if online and image crop exists
            if self.llm.is_online and chart.image_path:
                tbl_preview = "\n".join(
                    " | ".join(c.text for c in r) for r in tbl.rows[:12]
                )
                res = self.llm.analyze_json(
                    system_prompt=(
                        "Tu es un auditeur financier expert. Compare l'image du graphique avec le tableau fourni. "
                        "Réponds en JSON avec la liste des anomalies: "
                        '[{"label": "...", "chart_value": "...", "table_value": "...", "explanation": "..."}]. '
                        "Retourne [] si tout est cohérent."
                    ),
                    user_prompt=f"Titre graphique: {chart.title}\nTableau associé ({tbl.title}):\n{tbl_preview}",
                    image_paths=[chart.image_path],
                )
                if isinstance(res, list):
                    for item in res:
                        if isinstance(item, dict) and item.get("chart_value") != item.get("table_value"):
                            findings.append(
                                Finding(
                                    finding_id=f"chart_{uuid.uuid4().hex[:10]}",
                                    title=f"Écart graphique vs tableau : {item.get('label', chart.title)}",
                                    description=(
                                        f"Le graphique '{chart.title}' (p.{chart.page_number}) affiche {item.get('chart_value')} "
                                        f"contre {item.get('table_value')} dans le tableau '{tbl.title}' (p.{tbl.page_number}). "
                                        f"{item.get('explanation', '')}"
                                    ),
                                    diff_category=DiffCategory.VISUEL_GRAPHIQUE,
                                    control_type=ControlType.GRAPHIQUES_VS_TABLEAUX,
                                    automation_level=AutomationLevel.SEMI_AUTO_AI_HUMAN,
                                    severity=Severity.MAJOR,
                                    v0_value=str(item.get("table_value", "")),
                                    v1_value=str(item.get("chart_value", "")),
                                    v1_location=make_page_loc(doc, chart.page_number, chart.bbox, role, chart.title),
                                    extra_locations=[make_table_loc(doc, tbl, role)],
                                    confidence=0.87,
                                    human_prompt="Valider visuellement l'étiquette du graphique par rapport au tableau de référence.",
                                    requires_human_action=True,
                                )
                            )
                    continue

            # 2. Deterministic vector-label vs table comparison fallback
            if chart.extracted_labels:
                tbl_nums: dict[float, str] = {}
                for r in tbl.rows[1:]:
                    for c in r[1:]:
                        if c.numeric_value is not None:
                            tbl_nums[round(c.numeric_value, 2)] = f"{r[0].text}: {c.text}"

                chart_nums = []
                for lbl in chart.extracted_labels:
                    if chart.title and lbl in chart.title:
                        continue
                    chart_nums.extend(extract_numbers_from_text(lbl))
                has_unit_labels = any(cn.unit is not None or cn.is_percent for cn in chart_nums)
                for cn in chart_nums:
                    val = round(cn.value, 2)
                    # Ignore years and bare axis ticks when explicit data-label units exist
                    if 2015 <= val <= 2030 and not cn.is_percent and cn.unit is None:
                        continue
                    if has_unit_labels and cn.unit is None and not cn.is_percent:
                        continue
                    if tbl_nums and val not in tbl_nums:
                        closest = min(tbl_nums.keys(), key=lambda tv: abs(tv - val))
                        if closest != 0 and abs(closest - val) > 0.5:
                            findings.append(
                                Finding(
                                    finding_id=f"chart_{uuid.uuid4().hex[:10]}",
                                    title=f"Étiquette graphique incohérente avec tableau ('{chart.title or chart.figure_id}')",
                                    description=(
                                        f"Le graphique (p.{chart.page_number}) comporte l'étiquette '{cn.raw}' "
                                        f"alors que la valeur la plus proche dans le tableau '{tbl.title}' (p.{tbl.page_number}) "
                                        f"est {closest} ({tbl_nums[closest]})."
                                    ),
                                    diff_category=DiffCategory.VISUEL_GRAPHIQUE,
                                    control_type=ControlType.GRAPHIQUES_VS_TABLEAUX,
                                    automation_level=AutomationLevel.SEMI_AUTO_AI_HUMAN,
                                    severity=Severity.MAJOR,
                                    v0_value=str(closest),
                                    v1_value=cn.raw,
                                    numeric_delta=round(val - closest, 2),
                                    v1_location=make_page_loc(doc, chart.page_number, chart.bbox, role, chart.title or cn.raw),
                                    extra_locations=[make_table_loc(doc, tbl, role)],
                                    confidence=0.82,
                                    ai_rationale="Extraction des étiquettes vectorielles du graphique comparées au tableau associé.",
                                    human_prompt="Valider l'anomalie sur le graphique (étiquette de barre / camembert vs tableau).",
                                    requires_human_action=True,
                                )
                            )
        return findings

    # 11. Lien Finance / Durabilité (CSRD)
    def _check_finance_vs_csrd(
        self, doc: ParsedPDF, obs: list[_KPIObservation], role: str
    ) -> list[Finding]:
        findings: list[Finding] = []
        # Cross-check headcount (effectifs) between Finance/Social notes and CSRD/ESG section
        eff_obs = [o for o in obs if o.kpi_key == "effectifs"]
        esg_eff = [o for o in eff_obs if _CSRD_SECTION_RE.search(o.section_title)]
        fin_eff = [o for o in eff_obs if not _CSRD_SECTION_RE.search(o.section_title)]

        if esg_eff and fin_eff:
            e0, f0 = esg_eff[0], fin_eff[0]
            if abs(e0.value - f0.value) > max(5.0, 0.01 * max(abs(e0.value), 1.0)):
                findings.append(
                    Finding(
                        finding_id=f"csrd_{uuid.uuid4().hex[:10]}",
                        title="Incohérence Effectifs : section CSRD/ESG vs section Finance/Sociale",
                        description=(
                            f"La section CSRD ({e0.section_title}, p.{e0.location.page_number}) mentionne {e0.value:.0f} "
                            f"tandis que la section financière/sociale ({f0.section_title}, p.{f0.location.page_number}) indique {f0.value:.0f}."
                        ),
                        diff_category=DiffCategory.REGLEMENTAIRE_ESEF,
                        control_type=ControlType.LIEN_FINANCE_CSRD,
                        automation_level=AutomationLevel.SEMI_AUTO_AI_HUMAN,
                        severity=Severity.MAJOR,
                        v0_value=f"Finance p.{f0.location.page_number}: {f0.value:.0f}",
                        v1_value=f"CSRD p.{e0.location.page_number}: {e0.value:.0f}",
                        numeric_delta=round(e0.value - f0.value, 2),
                        v1_location=e0.location,
                        extra_locations=[f0.location],
                        confidence=0.86,
                        human_prompt="Valider si l'écart d'effectifs s'explique par le périmètre de consolidation CSRD (ex. ETP moyens vs inscrits en fin d'exercice).",
                        requires_human_action=True,
                    )
                )

        # Check Taxonomy CapEx / CA ratio vs absolute financial denominator
        ca_fin = next(
            (o for o in obs if o.kpi_key == "chiffre_affaires" and o.source_kind == "table" and not _CSRD_SECTION_RE.search(o.section_title)),
            None,
        )
        for tbl in doc.tables:
            if not _CSRD_SECTION_RE.search(tbl.title + " " + (tbl.section_title or "")):
                continue
            for row in tbl.rows[1:]:
                if not row:
                    continue
                lbl = row[0].text.lower()
                if "taxonomie" in lbl and ("ca" in lbl or "chiffre d'affaires" in lbl) and ca_fin:
                    # Look for an absolute CA taxonomy number and a % aligned/eligible number
                    abs_cell = next((c for c in row[1:] if c.numeric_value is not None and not c.is_percent), None)
                    pct_cell = next((c for c in row[1:] if c.numeric_value is not None and c.is_percent), None)
                    if abs_cell and pct_cell and ca_fin.value > 0:
                        implied_pct = round((_to_base_eur(abs_cell.numeric_value, abs_cell.unit_hint or tbl.unit_hint) / _to_base_eur(ca_fin.value, ca_fin.unit)) * 100.0, 2)
                        if abs(implied_pct - pct_cell.numeric_value) > 1.5:
                            findings.append(
                                Finding(
                                    finding_id=f"csrd_{uuid.uuid4().hex[:10]}",
                                    title="Ratio Taxonomie CA incohérent avec le CA consolidé",
                                    description=(
                                        f"Part Taxonomie affichée = {pct_cell.numeric_value:.1f} %, mais le montant ({abs_cell.text}) "
                                        f"rapporté au CA consolidé ({ca_fin.value} {ca_fin.unit or ''}) donne {implied_pct:.1f} %."
                                    ),
                                    diff_category=DiffCategory.REGLEMENTAIRE_ESEF,
                                    control_type=ControlType.LIEN_FINANCE_CSRD,
                                    automation_level=AutomationLevel.SEMI_AUTO_AI_HUMAN,
                                    severity=Severity.MAJOR,
                                    v1_value=f"{pct_cell.numeric_value:.1f} %",
                                    expected_value=f"{implied_pct:.1f} %",
                                    v1_location=make_table_loc(doc, tbl, role, pct_cell),
                                    extra_locations=[ca_fin.location],
                                    confidence=0.88,
                                    human_prompt="Valider le dénominateur Taxonomie (CA éligible vs CA consolidé IFRS).",
                                    requires_human_action=True,
                                )
                            )
        return findings

    def _llm_cross_check_pass(self, v0: ParsedPDF, v1: ParsedPDF) -> list[Finding]:
        # Summarize key tables & narrative claims for V1 to detect subtle semantic contradictions
        tbl_summaries = []
        for t in v1.tables[:10]:
            rows_txt = " | ".join(
                f"{r[0].text}: {r[1].text if len(r) > 1 else ''}" for r in t.rows[1:6] if r
            )
            tbl_summaries.append(f"[p.{t.page_number}] {t.title}: {rows_txt}")

        narr_blocks = [
            f"[p.{p.page_number}] {b.text[:300]}"
            for p in v1.pages[:15]
            for b in p.blocks
            if b.block_type == "paragraph" and any(ch.isdigit() for ch in b.text)
        ][:20]

        if not tbl_summaries or not narr_blocks:
            return []

        res = self.llm.analyze_json(
            system_prompt=(
                "Tu es un commissaire aux comptes vérifiant la cohérence interne d'un URD V1. "
                "Identifie uniquement les contradictions avérées entre le texte narratif et les tableaux ou entre sections. "
                "Format JSON: [{\"title\": \"...\", \"page_text\": 1, \"page_ref\": 2, \"description\": \"...\", \"type\": \"coherence_texte_tableau|cross_checks_inter_sections\"}]. "
                "Retourne [] s'il n'y a aucune contradiction."
            ),
            user_prompt="TABLEAUX:\n" + "\n".join(tbl_summaries) + "\n\nTEXTES:\n" + "\n".join(narr_blocks),
        )
        findings: list[Finding] = []
        if isinstance(res, list):
            for item in res[:5]:
                if not isinstance(item, dict):
                    continue
                pg = int(item.get("page_text") or 1)
                if not (1 <= pg <= v1.page_count):
                    pg = 1
                page = v1.pages[pg - 1]
                blk = page.blocks[0] if page.blocks else None
                if not blk:
                    continue
                ctype = (
                    ControlType.CROSS_CHECKS_INTER_SECTIONS
                    if item.get("type") == "cross_checks_inter_sections"
                    else ControlType.COHERENCE_TEXTE_TABLEAU
                )
                findings.append(
                    Finding(
                        finding_id=f"ai_{uuid.uuid4().hex[:10]}",
                        title=str(item.get("title", "Contradiction sémantique détectée par IA")),
                        description=str(item.get("description", "")),
                        diff_category=DiffCategory.CONTENU,
                        control_type=ctype,
                        automation_level=AutomationLevel.SEMI_AUTO_AI_HUMAN,
                        severity=Severity.MAJOR,
                        v1_location=make_block_loc(v1, blk, "v1"),
                        confidence=0.80,
                        ai_rationale="Analyse sémantique LLM inter-sections / texte vs tableau.",
                        human_prompt="Valider cette contradiction potentielle relevée par l'IA.",
                        requires_human_action=True,
                    )
                )
        return findings
