"""Automatic identification of V0, V1, and optional URD N-1 among uploaded PDFs."""

from __future__ import annotations

import re
from datetime import datetime

from urd_verifier.models.document import ParsedPDF
from urd_verifier.models.session import VersionDetectionResult, VersionSignal

_FRENCH_MONTHS = {
    "janvier": 1,
    "février": 2,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
    "decembre": 12,
}

_DATE_FR_RE = re.compile(
    r"\b(\d{1,2})\s+(janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|"
    r"septembre|octobre|novembre|d[eé]cembre)\s+(20\d{2})\b",
    re.IGNORECASE,
)
_DATE_NUM_RE = re.compile(r"\b(\d{2})[/\-](\d{2})[/\-](20\d{2})\b")
_URD_YEAR_RE = re.compile(
    r"(?i)(?:document\s+d['’]enregistrement\s+universel|urd|exercice)\s*(?:clos\s+le\s+31\s+d[eé]cembre\s+)?(20\d{2})"
)
_DRAFT_RE = re.compile(
    r"(?i)\b(v0(?:\.\d+)?|version\s*0(?:\.\d+)?|brouillon|projet|pr[eé]liminaire|draft|wip|à\s+compl[eé]ter|tbd)\b"
)
_V1_RE = re.compile(
    r"(?i)\b(v1(?:\.\d+)?|version\s*1(?:\.\d+)?|v2(?:\.\d+)?|final(?:e)?|d[eé]finiti(?:f|ve)|amend[eé]e?|d[eé]p[oô]t\s+amf)\b"
)


def _parse_pdf_date(raw: str) -> datetime | None:
    if not raw:
        return None
    m = re.search(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?", raw)
    if m:
        try:
            return datetime(
                int(m.group(1)),
                int(m.group(2)),
                int(m.group(3)),
                int(m.group(4) or 0),
                int(m.group(5) or 0),
            )
        except ValueError:
            return None
    return None


def _extract_cover_dates(doc: ParsedPDF) -> list[tuple[datetime, str, int, object]]:
    found: list[tuple[datetime, str, int, object]] = []
    for page in doc.pages[:3]:
        for blk in page.blocks:
            for m in _DATE_FR_RE.finditer(blk.text):
                day = int(m.group(1))
                month = _FRENCH_MONTHS.get(m.group(2).lower(), 1)
                year = int(m.group(3))
                try:
                    dt = datetime(year, month, day)
                    found.append((dt, m.group(0), page.page_number, blk.bbox))
                except ValueError:
                    pass
            for m in _DATE_NUM_RE.finditer(blk.text):
                try:
                    dt = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                    found.append((dt, m.group(0), page.page_number, blk.bbox))
                except ValueError:
                    pass
    return found


def _extract_urd_fiscal_year(doc: ParsedPDF) -> int | None:
    years: list[int] = []
    for page in doc.pages[:3]:
        for m in _URD_YEAR_RE.finditer(page.raw_text):
            years.append(int(m.group(1)))
    if years:
        return max(set(years), key=years.count)
    # Check filename
    m = re.search(r"(20[12]\d)", doc.filename)
    if m:
        return int(m.group(1))
    return None


class VersionDetector:
    """Identifies which uploaded PDF is V0, V1, and optional URD N-1."""

    def detect(self, docs: list[ParsedPDF]) -> VersionDetectionResult:
        if len(docs) < 2:
            raise ValueError("At least 2 PDF documents are required to detect V0 and V1.")

        signals: list[VersionSignal] = []
        urd_n_minus_1: ParsedPDF | None = None
        candidates = list(docs)

        # Step 1: If >= 3 documents, check if one is an older fiscal year (URD N-1)
        if len(candidates) >= 3:
            fiscal_years = {d.filename: _extract_urd_fiscal_year(d) for d in candidates}
            valid_years = [y for y in fiscal_years.values() if y is not None]
            if valid_years:
                max_year = max(valid_years)
                older = [d for d in candidates if fiscal_years[d.filename] == max_year - 1]
                if len(older) == 1:
                    urd_n_minus_1 = older[0]
                    candidates = [d for d in candidates if d.filename != urd_n_minus_1.filename]
                    signals.append(
                        VersionSignal(
                            doc_filename=urd_n_minus_1.filename,
                            signal_type="fiscal_year",
                            evidence=f"Exercice fiscal URD détecté : {max_year - 1} (< {max_year})",
                            favors="urd_n_minus_1",
                            weight=5.0,
                            page_number=1,
                        )
                    )

        # If still > 2 docs, pick top 2 by version scoring, or check explicit N-1 filename
        if len(candidates) > 2:
            for d in list(candidates):
                if re.search(r"(?i)(n[-_]?1|precedent|prev)", d.filename) and urd_n_minus_1 is None:
                    urd_n_minus_1 = d
                    candidates.remove(d)
                    signals.append(
                        VersionSignal(
                            doc_filename=d.filename,
                            signal_type="filename",
                            evidence="Nom de fichier indique l'URD N-1",
                            favors="urd_n_minus_1",
                            weight=4.0,
                        )
                    )
                    break

        doc_a, doc_b = candidates[0], candidates[1]
        # Score: negative -> favors V0, positive -> favors V1
        scores: dict[str, float] = {doc_a.filename: 0.0, doc_b.filename: 0.0}

        for doc in (doc_a, doc_b):
            fname = doc.filename.lower()
            # 1. Filename heuristics
            if re.search(r"(?:^|[_\-\s])v0(?:\.\d+)?(?:[_\-\s.]|$)", fname) or any(
                k in fname for k in ("draft", "brouillon", "projet", "initial")
            ):
                scores[doc.filename] -= 4.0
                signals.append(
                    VersionSignal(
                        doc_filename=doc.filename,
                        signal_type="filename",
                        evidence=f"Nom de fichier '{doc.filename}' évoque une version initiale / V0",
                        favors="v0",
                        weight=4.0,
                    )
                )
            if re.search(r"(?:^|[_\-\s])v[1-9](?:\.\d+)?(?:[_\-\s.]|$)", fname) or any(
                k in fname for k in ("final", "definitif", "valide", "amf", "corrige")
            ):
                scores[doc.filename] += 4.0
                signals.append(
                    VersionSignal(
                        doc_filename=doc.filename,
                        signal_type="filename",
                        evidence=f"Nom de fichier '{doc.filename}' évoque une version ultérieure / V1",
                        favors="v1",
                        weight=4.0,
                    )
                )

            # 2. Cover & headers/footers version markers (pages 1..3)
            for page in doc.pages[:3]:
                for blk in page.blocks:
                    if _DRAFT_RE.search(blk.text):
                        m = _DRAFT_RE.search(blk.text)
                        scores[doc.filename] -= 3.5
                        signals.append(
                            VersionSignal(
                                doc_filename=doc.filename,
                                signal_type="cover_version",
                                evidence=f"Mention '{m.group(0)}' détectée page {page.page_number}",
                                favors="v0",
                                weight=3.5,
                                page_number=page.page_number,
                                bbox=blk.bbox,
                            )
                        )
                    if _V1_RE.search(blk.text):
                        m = _V1_RE.search(blk.text)
                        scores[doc.filename] += 3.5
                        signals.append(
                            VersionSignal(
                                doc_filename=doc.filename,
                                signal_type="cover_version",
                                evidence=f"Mention '{m.group(0)}' détectée page {page.page_number}",
                                favors="v1",
                                weight=3.5,
                                page_number=page.page_number,
                                bbox=blk.bbox,
                            )
                        )

        # 3. Compare cover dates
        dates_a = _extract_cover_dates(doc_a)
        dates_b = _extract_cover_dates(doc_b)
        if dates_a and dates_b:
            max_da = max(dates_a, key=lambda x: x[0])
            max_db = max(dates_b, key=lambda x: x[0])
            if max_da[0] < max_db[0]:
                scores[doc_a.filename] -= 3.0
                scores[doc_b.filename] += 3.0
                signals.append(
                    VersionSignal(
                        doc_filename=doc_a.filename,
                        signal_type="cover_date",
                        evidence=f"Date documentaire antérieure : {max_da[1]}",
                        favors="v0",
                        weight=3.0,
                        page_number=max_da[2],
                        bbox=max_da[3],  # type: ignore[arg-type]
                    )
                )
                signals.append(
                    VersionSignal(
                        doc_filename=doc_b.filename,
                        signal_type="cover_date",
                        evidence=f"Date documentaire postérieure : {max_db[1]}",
                        favors="v1",
                        weight=3.0,
                        page_number=max_db[2],
                        bbox=max_db[3],  # type: ignore[arg-type]
                    )
                )
            elif max_db[0] < max_da[0]:
                scores[doc_b.filename] -= 3.0
                scores[doc_a.filename] += 3.0
                signals.append(
                    VersionSignal(
                        doc_filename=doc_b.filename,
                        signal_type="cover_date",
                        evidence=f"Date documentaire antérieure : {max_db[1]}",
                        favors="v0",
                        weight=3.0,
                        page_number=max_db[2],
                        bbox=max_db[3],  # type: ignore[arg-type]
                    )
                )
                signals.append(
                    VersionSignal(
                        doc_filename=doc_a.filename,
                        signal_type="cover_date",
                        evidence=f"Date documentaire postérieure : {max_da[1]}",
                        favors="v1",
                        weight=3.0,
                        page_number=max_da[2],
                        bbox=max_da[3],  # type: ignore[arg-type]
                    )
                )

        # 4. Compare PDF metadata creation/modDate
        meta_da = _parse_pdf_date(doc_a.metadata.get("modDate") or doc_a.metadata.get("creationDate", ""))
        meta_db = _parse_pdf_date(doc_b.metadata.get("modDate") or doc_b.metadata.get("creationDate", ""))
        if meta_da and meta_db and meta_da != meta_db:
            if meta_da < meta_db:
                scores[doc_a.filename] -= 1.5
                scores[doc_b.filename] += 1.5
                signals.append(
                    VersionSignal(
                        doc_filename=doc_b.filename,
                        signal_type="metadata_date",
                        evidence=f"Métadonnée PDF modDate plus récente ({meta_db.isoformat()})",
                        favors="v1",
                        weight=1.5,
                    )
                )
            else:
                scores[doc_b.filename] -= 1.5
                scores[doc_a.filename] += 1.5
                signals.append(
                    VersionSignal(
                        doc_filename=doc_a.filename,
                        signal_type="metadata_date",
                        evidence=f"Métadonnée PDF modDate plus récente ({meta_da.isoformat()})",
                        favors="v1",
                        weight=1.5,
                    )
                )

        # 5. Content completeness / placeholders (e.g., TBD / À compléter / fewer pages)
        for doc in (doc_a, doc_b):
            full_text = "\n".join(p.raw_text for p in doc.pages)
            placeholders = len(re.findall(r"(?i)\[?\b(?:à\s+compl[eé]ter|tbd|xx+|en\s+attente)\b\]?", full_text))
            if placeholders > 0:
                scores[doc.filename] -= min(3.0, placeholders * 1.0)
                signals.append(
                    VersionSignal(
                        doc_filename=doc.filename,
                        signal_type="content_progression",
                        evidence=f"{placeholders} zone(s) provisoire(s) ('À compléter' / 'TBD') détectée(s)",
                        favors="v0",
                        weight=min(3.0, float(placeholders)),
                    )
                )

        # Decide V0 and V1
        if scores[doc_a.filename] <= scores[doc_b.filename]:
            v0_doc, v1_doc = doc_a, doc_b
        else:
            v0_doc, v1_doc = doc_b, doc_a

        margin = abs(scores[v1_doc.filename] - scores[v0_doc.filename])
        if margin == 0:
            confidence = 0.50
        elif margin < 2.0:
            confidence = 0.62
        elif margin < 5.0:
            confidence = 0.80
        else:
            confidence = min(0.99, 0.85 + margin * 0.015)

        needs_confirm = confidence < 0.70
        rationale = (
            f"V0 identifiée comme '{v0_doc.filename}' (score {scores[v0_doc.filename]:+.1f}) "
            f"et V1 identifiée comme '{v1_doc.filename}' (score {scores[v1_doc.filename]:+.1f})"
        )
        if urd_n_minus_1:
            rationale += f" ; URD N-1 détecté : '{urd_n_minus_1.filename}'."

        return VersionDetectionResult(
            v0_filename=v0_doc.filename,
            v1_filename=v1_doc.filename,
            urd_n_minus_1_filename=urd_n_minus_1.filename if urd_n_minus_1 else None,
            confidence=round(confidence, 3),
            needs_human_confirmation=needs_confirm,
            rationale=rationale,
            signals=signals,
        )
