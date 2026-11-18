"""Hybrid PyMuPDF + pdfplumber PDF parser with exact bounding boxes, styles, tables, and charts."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

import pymupdf as fitz  # PyMuPDF
import pdfplumber

from urd_verifier.models.document import (
    BoundingBox,
    ChartFigure,
    ConcordanceEntry,
    CrossReference,
    PageData,
    ParsedPDF,
    SectionNode,
    TableCell,
    TableData,
    TextBlock,
    TextSpan,
)
from .number_parser import detect_unit_in_text, parse_financial_number

_SECTION_HEADING_RE = re.compile(
    r"^(?:(?:CHAPITRE|CHAPTER|SECTION|PARTIE|NOTE)\s+\d+(?:\.\d+)*|"
    r"\d+(?:\.\d+){0,3}\s+[A-ZÀ-Ÿ])",
    re.IGNORECASE,
)

_CROSS_REF_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "note",
        re.compile(
            r"(?i)\b(?:cf\.?|voir|se\s+référer\s+à\s+la|selon\s+la)\s+note\s+(\d+(?:\.\d+)?)\b"
        ),
    ),
    (
        "page",
        re.compile(r"(?i)\b(?:cf\.?|voir)\s+(?:en\s+)?page\s+(\d{1,4})\b|\bp\.\s*(\d{1,4})\b"),
    ),
    (
        "section",
        re.compile(r"(?i)\b(?:cf\.?|voir)\s+(?:la\s+)?section\s+(\d+(?:\.\d+)*)\b"),
    ),
    (
        "annexe",
        re.compile(r"(?i)\b(?:cf\.?|voir)\s+(?:l['’])?annexe\s+([A-Z0-9]+(?:\.\d+)?)\b"),
    ),
    (
        "table",
        re.compile(r"(?i)\b(?:cf\.?|voir)\s+(?:le\s+)?tableau\s+(\d+(?:\.\d+)?)\b"),
    ),
]

_ESEF_RE = re.compile(
    r"(?i)\b(i?xbrl|esef|esma|rts\s+esef|balisage|taxonomy|taxonomie\s+esef|xhtml)\b"
)

_CHART_TITLE_RE = re.compile(
    r"(?i)\b(graphique|figure|diagramme|camembert|histogramme|chart|répartition\s+du|évolution\s+du)\b"
)


def _normalize_title(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9àâäéèêëïîôöùûüç\s]", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _color_int_to_hex(color: int | None) -> str:
    if color is None:
        return "#000000"
    return f"#{color & 0xFFFFFF:06x}"


def _rects_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float], margin: float = 2.0) -> bool:
    return not (
        a[2] < b[0] + margin
        or a[0] > b[2] - margin
        or a[3] < b[1] + margin
        or a[1] > b[3] - margin
    )


class PDFParser:
    """Parses enterprise URD PDFs preserving full layout, styles, tables, and bounding boxes."""

    def parse(self, file_path: str | Path, render_dir: Path | None = None) -> ParsedPDF:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {path}")

        doc_id = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
        fitz_doc = fitz.open(str(path))
        plumber_doc = pdfplumber.open(str(path))

        if render_dir:
            render_dir.mkdir(parents=True, exist_ok=True)

        metadata = {
            k: str(v) for k, v in (fitz_doc.metadata or {}).items() if v is not None
        }

        pages: list[PageData] = []
        all_tables: list[TableData] = []
        all_cross_refs: list[CrossReference] = []
        all_concordance: list[ConcordanceEntry] = []
        all_charts: list[ChartFigure] = []
        esef_signals: list[dict[str, str | int]] = []

        # Track font sizes across document to identify headings robustly
        font_sizes: list[float] = []
        for p in fitz_doc:
            d = p.get_text("dict")
            for b in d.get("blocks", []):
                if b.get("type") != 0:
                    continue
                for line in b.get("lines", []):
                    for span in line.get("spans", []):
                        if span.get("text", "").strip():
                            font_sizes.append(float(span.get("size", 10.0)))

        body_font_size = sorted(font_sizes)[len(font_sizes) // 2] if font_sizes else 10.0

        try:
            for page_idx in range(len(fitz_doc)):
                page_num = page_idx + 1
                fpage = fitz_doc[page_idx]
                ppage = plumber_doc.pages[page_idx]
                pw = float(fpage.rect.width)
                ph = float(fpage.rect.height)

                # 1. Extract tables first so we know their bounding boxes
                page_tables, table_rects = self._extract_page_tables(
                    fpage, ppage, page_num, pw, ph
                )

                # 2. Extract text blocks & spans
                text_dict = fpage.get_text("dict")
                raw_text = fpage.get_text("text") or ""
                page_blocks: list[TextBlock] = []
                header_parts: list[str] = []
                footer_parts: list[str] = []

                for b_idx, block in enumerate(text_dict.get("blocks", [])):
                    if block.get("type") != 0:
                        continue
                    bx0, by0, bx1, by1 = block["bbox"]

                    spans: list[TextSpan] = []
                    line_texts: list[str] = []
                    for line in block.get("lines", []):
                        l_chars: list[str] = []
                        for sp in line.get("spans", []):
                            stext = sp.get("text", "")
                            if not stext:
                                continue
                            s_bbox = BoundingBox.from_rect(*sp["bbox"], pw, ph)
                            fname = sp.get("font", "")
                            fsize = float(sp.get("size", 10.0))
                            flags = int(sp.get("flags", 0))
                            is_bold = bool(flags & 16) or ("bold" in fname.lower())
                            is_italic = bool(flags & 2) or (
                                "italic" in fname.lower() or "oblique" in fname.lower()
                            )
                            color_hex = _color_int_to_hex(sp.get("color"))
                            spans.append(
                                TextSpan(
                                    text=stext,
                                    bbox=s_bbox,
                                    font_name=fname,
                                    font_size=round(fsize, 2),
                                    is_bold=is_bold,
                                    is_italic=is_italic,
                                    color_hex=color_hex,
                                )
                            )
                            l_chars.append(stext)
                        joined_line = "".join(l_chars).strip()
                        if joined_line:
                            line_texts.append(joined_line)

                    block_text = "\n".join(line_texts).strip()
                    if not block_text or not spans:
                        continue

                    # Skip blocks completely inside extracted tables
                    if any(_rects_overlap((bx0, by0, bx1, by1), tr, margin=4.0) for tr in table_rects):
                        continue

                    # Dominant span style
                    dominant_span = max(spans, key=lambda s: len(s.text))
                    bbox = BoundingBox.from_rect(bx0, by0, bx1, by1, pw, ph)

                    # Classify block type (header/footer/heading/paragraph)
                    btype = "paragraph"
                    if by1 < ph * 0.085:
                        btype = "header"
                        header_parts.append(block_text)
                    elif by0 > ph * 0.91:
                        btype = "footer"
                        footer_parts.append(block_text)
                    elif self._is_heading(block_text, dominant_span, body_font_size):
                        btype = "heading"
                    elif _CHART_TITLE_RE.search(block_text) and len(block_text) < 180:
                        btype = "caption"

                    tb = TextBlock(
                        block_id=f"{doc_id}_p{page_num}_b{b_idx}",
                        page_number=page_num,
                        bbox=bbox,
                        text=block_text,
                        block_type=btype,
                        primary_font=dominant_span.font_name,
                        primary_size=dominant_span.font_size,
                        is_bold=dominant_span.is_bold,
                        is_italic=dominant_span.is_italic,
                        color_hex=dominant_span.color_hex,
                        spans=spans,
                    )
                    page_blocks.append(tb)

                    # Detect cross-references
                    for ref_type, pattern in _CROSS_REF_PATTERNS:
                        for m in pattern.finditer(block_text):
                            target = next((g for g in m.groups() if g is not None), "")
                            all_cross_refs.append(
                                CrossReference(
                                    ref_id=f"ref_{uuid.uuid4().hex[:8]}",
                                    page_number=page_num,
                                    bbox=bbox,
                                    raw_text=m.group(0),
                                    ref_type=ref_type,  # type: ignore[arg-type]
                                    target_identifier=target,
                                )
                            )

                    # Detect ESEF signals
                    if _ESEF_RE.search(block_text):
                        esef_signals.append(
                            {
                                "page_number": page_num,
                                "snippet": block_text[:280],
                            }
                        )

                # Attach titles & unit hints to tables from nearby preceding blocks
                self._enrich_tables_with_titles(page_tables, page_blocks)
                all_tables.extend(page_tables)

                # Check if this page contains a concordance / summary table
                if self._is_concordance_page(raw_text):
                    all_concordance.extend(
                        self._extract_concordance_entries(page_tables, page_blocks, page_num)
                    )

                # Extract visual chart regions (images or drawing clusters)
                page_charts = self._extract_page_charts(
                    fpage, page_num, pw, ph, page_blocks, render_dir, doc_id
                )
                all_charts.extend(page_charts)

                # Extract displayed page number from footer/header
                displayed_pg = self._extract_displayed_page_num(
                    " ".join(footer_parts + header_parts)
                )

                pages.append(
                    PageData(
                        page_number=page_num,
                        width=round(pw, 2),
                        height=round(ph, 2),
                        raw_text=raw_text,
                        blocks=page_blocks,
                        header_text=" | ".join(header_parts),
                        footer_text=" | ".join(footer_parts),
                        displayed_page_number=displayed_pg,
                    )
                )
        finally:
            fitz_doc.close()
            plumber_doc.close()

        # Build hierarchical section tree and assign section_id to blocks/tables
        sections = self._build_sections(pages, body_font_size)
        self._assign_sections(pages, all_tables, sections)

        return ParsedPDF(
            doc_id=doc_id,
            filename=path.name,
            file_path=str(path.resolve()),
            page_count=len(pages),
            metadata=metadata,
            pages=pages,
            sections=sections,
            tables=all_tables,
            cross_refs=all_cross_refs,
            concordance_entries=all_concordance,
            charts=all_charts,
            esef_signals=esef_signals,
        )

    def _is_heading(self, text: str, span: TextSpan, body_size: float) -> bool:
        single_line = text.replace("\n", " ").strip()
        if len(single_line) > 160:
            return False
        if span.font_size >= body_size + 1.5:
            return True
        if span.is_bold and len(single_line) <= 110 and (
            _SECTION_HEADING_RE.match(single_line)
            or single_line.isupper()
            or single_line.startswith(("Note ", "Chapitre ", "Section ", "Annexe ", "Table "))
        ):
            return True
        return False

    def _extract_page_tables(
        self,
        fpage: fitz.Page,
        ppage: pdfplumber.page.Page,
        page_num: int,
        pw: float,
        ph: float,
    ) -> tuple[list[TableData], list[tuple[float, float, float, float]]]:
        tables: list[TableData] = []
        table_rects: list[tuple[float, float, float, float]] = []

        # Primary: pdfplumber table finder (preserves exact reading order & spaces in cells + cell bboxes)
        try:
            p_tables = ppage.find_tables()
        except Exception:
            p_tables = []

        for t_idx, pt in enumerate(p_tables):
            extracted = pt.extract()
            if not extracted or len(extracted) < 2:
                continue
            tbbox = tuple(pt.bbox)
            table_rects.append(tbbox)  # type: ignore[arg-type]

            headers = [str(c or "").strip().replace("\n", " ") for c in extracted[0]]
            header_unit, _ = detect_unit_in_text(" ".join(headers))
            rows: list[list[TableCell]] = []

            for r_idx, row_vals in enumerate(extracted):
                row_cells: list[TableCell] = []
                cell_boxes = pt.rows[r_idx].cells if r_idx < len(pt.rows) else []
                for c_idx, val in enumerate(row_vals):
                    cell_txt = str(val or "").strip().replace("\n", " ")
                    c_bbox = None
                    if c_idx < len(cell_boxes) and cell_boxes[c_idx] is not None:
                        c_bbox = BoundingBox.from_rect(*cell_boxes[c_idx], pw, ph)
                    else:
                        c_bbox = BoundingBox.from_rect(*tbbox, pw, ph)
                    parsed_num = parse_financial_number(cell_txt)
                    is_pct = parsed_num.is_percent if parsed_num else ("%" in cell_txt)
                    row_cells.append(
                        TableCell(
                            row_idx=r_idx,
                            col_idx=c_idx,
                            text=cell_txt,
                            numeric_value=parsed_num.value if parsed_num else None,
                            unit_hint=(parsed_num.unit if parsed_num and parsed_num.unit else header_unit),
                            is_percent=is_pct,
                            is_header=(r_idx == 0),
                            bbox=c_bbox,
                        )
                    )
                rows.append(row_cells)

            tables.append(
                TableData(
                    table_id=f"p{page_num}_t{t_idx}",
                    page_number=page_num,
                    bbox=BoundingBox.from_rect(*tbbox, pw, ph),
                    unit_hint=header_unit or "",
                    headers=headers,
                    rows=rows,
                )
            )

        # Fallback: PyMuPDF table finder if pdfplumber found 0 tables on this page
        if not tables:
            try:
                finder = fpage.find_tables()
                found_tables = finder.tables if finder else []
            except Exception:
                found_tables = []

            for t_idx, ft in enumerate(found_tables):
                extracted = ft.extract()
                if not extracted or len(extracted) < 2:
                    continue
                tbbox = tuple(ft.bbox)
                table_rects.append(tbbox)  # type: ignore[arg-type]
                headers = [str(c or "").strip().replace("\n", " ") for c in extracted[0]]
                header_unit, _ = detect_unit_in_text(" ".join(headers))
                rows = []
                for r_idx, row_vals in enumerate(extracted):
                    row_cells = []
                    cell_boxes = ft.rows[r_idx].cells if r_idx < len(ft.rows) else []
                    for c_idx, val in enumerate(row_vals):
                        cell_txt = str(val or "").strip().replace("\n", " ")
                        c_bbox = (
                            BoundingBox.from_rect(*cell_boxes[c_idx], pw, ph)
                            if c_idx < len(cell_boxes) and cell_boxes[c_idx] is not None
                            else BoundingBox.from_rect(*tbbox, pw, ph)
                        )
                        parsed_num = parse_financial_number(cell_txt)
                        row_cells.append(
                            TableCell(
                                row_idx=r_idx,
                                col_idx=c_idx,
                                text=cell_txt,
                                numeric_value=parsed_num.value if parsed_num else None,
                                unit_hint=(parsed_num.unit if parsed_num and parsed_num.unit else header_unit),
                                is_percent=parsed_num.is_percent if parsed_num else ("%" in cell_txt),
                                is_header=(r_idx == 0),
                                bbox=c_bbox,
                            )
                        )
                    rows.append(row_cells)
                tables.append(
                    TableData(
                        table_id=f"p{page_num}_ft{t_idx}",
                        page_number=page_num,
                        bbox=BoundingBox.from_rect(*tbbox, pw, ph),
                        unit_hint=header_unit or "",
                        headers=headers,
                        rows=rows,
                    )
                )

        return tables, table_rects

    def _enrich_tables_with_titles(
        self, tables: list[TableData], blocks: list[TextBlock]
    ) -> None:
        for tbl in tables:
            candidates = [
                b
                for b in blocks
                if b.block_type not in {"header", "footer"}
                and b.bbox.y1 <= tbl.bbox.y0 + 8
                and (tbl.bbox.y0 - b.bbox.y1) < 75
            ]
            if candidates:
                closest = max(candidates, key=lambda b: b.bbox.y1)
                tbl.title = closest.text.replace("\n", " ").strip()
                unit, _ = detect_unit_in_text(tbl.title)
                if unit and not tbl.unit_hint:
                    tbl.unit_hint = unit

    def _is_concordance_page(self, raw_text: str) -> bool:
        low = raw_text.lower()
        return (
            "table de concordance" in low
            or "concordance amf" in low
            or "sommaire du document" in low
        )

    def _extract_concordance_entries(
        self, tables: list[TableData], blocks: list[TextBlock], page_num: int
    ) -> list[ConcordanceEntry]:
        entries: list[ConcordanceEntry] = []
        for tbl in tables:
            for row in tbl.rows[1:]:
                if len(row) < 2:
                    continue
                label = row[0].text.strip()
                page_col = row[-1].text.strip()
                if not label:
                    continue
                nums = [int(n) for n in re.findall(r"\b(\d{1,4})\b", page_col)]
                bbox = row[0].bbox or tbl.bbox
                entries.append(
                    ConcordanceEntry(
                        entry_id=f"conc_p{page_num}_{len(entries)}",
                        page_number=page_num,
                        bbox=bbox,
                        label=label,
                        declared_pages=nums,
                    )
                )
        # Fallback: line-based concordance entries like "1. Facteurs de risques ........ 14"
        if not entries:
            for b in blocks:
                for line in b.text.splitlines():
                    m = re.match(r"^(.{5,90}?)\s*(?:\.{2,}|–|-|\s{2,})\s*(?:p\.?\s*)?(\d{1,4})\s*$", line)
                    if m:
                        entries.append(
                            ConcordanceEntry(
                                entry_id=f"conc_p{page_num}_{len(entries)}",
                                page_number=page_num,
                                bbox=b.bbox,
                                label=m.group(1).strip(),
                                declared_pages=[int(m.group(2))],
                            )
                        )
        return entries

    def _extract_page_charts(
        self,
        fpage: fitz.Page,
        page_num: int,
        pw: float,
        ph: float,
        blocks: list[TextBlock],
        render_dir: Path | None,
        doc_id: str,
    ) -> list[ChartFigure]:
        charts: list[ChartFigure] = []

        # 1. Embedded raster images
        for img_idx, img in enumerate(fpage.get_images(full=True)):
            xref = img[0]
            for r_idx, rect in enumerate(fpage.get_image_rects(xref)):
                if rect.width < 80 or rect.height < 60:
                    continue  # Ignore tiny logos/icons
                bbox = BoundingBox.from_rect(rect.x0, rect.y0, rect.x1, rect.y1, pw, ph)
                title = self._find_nearest_caption(bbox, blocks)
                img_path = None
                if render_dir:
                    pix = fpage.get_pixmap(clip=rect, dpi=150)
                    out = render_dir / f"{doc_id}_p{page_num}_img{img_idx}_{r_idx}.png"
                    pix.save(str(out))
                    img_path = str(out)
                charts.append(
                    ChartFigure(
                        figure_id=f"fig_p{page_num}_img{img_idx}_{r_idx}",
                        page_number=page_num,
                        bbox=bbox,
                        title=title,
                        image_path=img_path,
                    )
                )

        # 2. Vector chart regions (e.g. ReportLab/Matplotlib vector bar/pie charts with captions)
        caption_blocks = [
            b for b in blocks if b.block_type == "caption" or _CHART_TITLE_RE.search(b.text)
        ]
        drawings = fpage.get_drawings()
        if caption_blocks and drawings:
            for c_idx, cb in enumerate(caption_blocks):
                # Look for vector drawings within 240pt below or above the caption
                region = fitz.Rect(
                    max(0, cb.bbox.x0 - 40),
                    max(0, cb.bbox.y0 - 20),
                    min(pw, max(cb.bbox.x1 + 200, pw * 0.85)),
                    min(ph, cb.bbox.y1 + 240),
                )
                region_drawings = [
                    d for d in drawings if region.intersects(fitz.Rect(d["rect"]))
                ]
                if len(region_drawings) >= 3:
                    # Compute union rect of vector chart elements
                    ux0 = min(d["rect"][0] for d in region_drawings)
                    uy0 = min(d["rect"][1] for d in region_drawings)
                    ux1 = max(d["rect"][2] for d in region_drawings)
                    uy1 = max(d["rect"][3] for d in region_drawings)
                    chart_rect = fitz.Rect(
                        min(ux0, cb.bbox.x0),
                        min(uy0, cb.bbox.y0),
                        max(ux1, cb.bbox.x1),
                        max(uy1, cb.bbox.y1),
                    )
                    # Collect individual span labels inside chart rect so axis ticks stay separate from bar labels
                    labels: list[str] = []
                    for b in blocks:
                        if _rects_overlap(
                            (b.bbox.x0, b.bbox.y0, b.bbox.x1, b.bbox.y1),
                            (chart_rect.x0, chart_rect.y0, chart_rect.x1, chart_rect.y1),
                            margin=0.0,
                        ):
                            for sp in b.spans:
                                st = sp.text.strip()
                                if st:
                                    labels.append(st)
                    img_path = None
                    if render_dir:
                        pix = fpage.get_pixmap(clip=chart_rect, dpi=150)
                        out = render_dir / f"{doc_id}_p{page_num}_vec{c_idx}.png"
                        pix.save(str(out))
                        img_path = str(out)
                    charts.append(
                        ChartFigure(
                            figure_id=f"fig_p{page_num}_vec{c_idx}",
                            page_number=page_num,
                            bbox=BoundingBox.from_rect(
                                chart_rect.x0, chart_rect.y0, chart_rect.x1, chart_rect.y1, pw, ph
                            ),
                            title=cb.text.replace("\n", " ").strip(),
                            extracted_labels=labels,
                            image_path=img_path,
                        )
                    )

        return charts

    def _find_nearest_caption(self, bbox: BoundingBox, blocks: list[TextBlock]) -> str:
        candidates = [
            b
            for b in blocks
            if abs(b.bbox.y1 - bbox.y0) < 50 or abs(b.bbox.y0 - bbox.y1) < 40
        ]
        if not candidates:
            return ""
        best = min(
            candidates,
            key=lambda b: min(abs(b.bbox.y1 - bbox.y0), abs(b.bbox.y0 - bbox.y1)),
        )
        return best.text.replace("\n", " ").strip()

    def _extract_displayed_page_num(self, text: str) -> int | None:
        if not text:
            return None
        m = re.search(r"(?i)(?:page|p\.?)\s*(\d{1,4})\b", text)
        if m:
            return int(m.group(1))
        m2 = re.search(r"\b(\d{1,4})\b\s*$", text.strip())
        if m2:
            val = int(m2.group(1))
            if 1 <= val <= 999:
                return val
        return None

    def _build_sections(
        self, pages: list[PageData], body_font_size: float
    ) -> list[SectionNode]:
        sections: list[SectionNode] = []
        for page in pages:
            for blk in page.blocks:
                if blk.block_type == "heading":
                    title = blk.text.replace("\n", " ").strip()
                    level = 1 if blk.primary_size >= body_font_size + 3.5 else 2
                    sections.append(
                        SectionNode(
                            section_id=f"sec_{len(sections) + 1}",
                            level=level,
                            title=title,
                            normalized_title=_normalize_title(title),
                            page_start=page.page_number,
                            page_end=page.page_number,
                            bbox=blk.bbox,
                        )
                    )
        # Update page_end for each section
        for i, sec in enumerate(sections):
            if i + 1 < len(sections):
                sec.page_end = max(sec.page_start, sections[i + 1].page_start)
            else:
                sec.page_end = pages[-1].page_number if pages else sec.page_start
        return sections

    def _assign_sections(
        self,
        pages: list[PageData],
        tables: list[TableData],
        sections: list[SectionNode],
    ) -> None:
        if not sections:
            return
        current_sec: SectionNode | None = None
        sec_by_start = {(s.page_start, s.bbox.y0): s for s in sections}

        for page in pages:
            for blk in sorted(page.blocks, key=lambda b: b.bbox.y0):
                key = (page.page_number, blk.bbox.y0)
                if key in sec_by_start:
                    current_sec = sec_by_start[key]
                if current_sec is not None:
                    blk.section_id = current_sec.section_id
                    blk.section_title = current_sec.title

        for tbl in tables:
            # Find latest section starting before or at this table
            matching = [
                s
                for s in sections
                if s.page_start < tbl.page_number
                or (s.page_start == tbl.page_number and s.bbox.y0 <= tbl.bbox.y0 + 5)
            ]
            if matching:
                sec = matching[-1]
                tbl.section_id = sec.section_id
                tbl.section_title = sec.title
