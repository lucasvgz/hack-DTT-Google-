"""Document structural models with exact PDF coordinates for UI highlighting."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """Exact coordinates in PDF points (top-left origin) plus normalized [0..1] ratios."""

    x0: float
    y0: float
    x1: float
    y1: float
    nx0: float = 0.0
    ny0: float = 0.0
    nx1: float = 0.0
    ny1: float = 0.0

    @classmethod
    def from_rect(
        cls, x0: float, y0: float, x1: float, y1: float, page_width: float, page_height: float
    ) -> "BoundingBox":
        pw = page_width if page_width > 0 else 1.0
        ph = page_height if page_height > 0 else 1.0
        return cls(
            x0=round(x0, 2),
            y0=round(y0, 2),
            x1=round(x1, 2),
            y1=round(y1, 2),
            nx0=round(max(0.0, min(1.0, x0 / pw)), 4),
            ny0=round(max(0.0, min(1.0, y0 / ph)), 4),
            nx1=round(max(0.0, min(1.0, x1 / pw)), 4),
            ny1=round(max(0.0, min(1.0, y1 / ph)), 4),
        )


class TextSpan(BaseModel):
    """Lowest-level styled text span for exact font/style ('forme') diffing."""

    text: str
    bbox: BoundingBox
    font_name: str = ""
    font_size: float = 0.0
    is_bold: bool = False
    is_italic: bool = False
    color_hex: str = "#000000"


class TextBlock(BaseModel):
    """Logical text block (paragraph, heading, header, footer, caption) with position."""

    block_id: str
    page_number: int  # 1-indexed
    bbox: BoundingBox
    text: str
    block_type: Literal["heading", "paragraph", "header", "footer", "caption", "list_item"] = (
        "paragraph"
    )
    section_id: str | None = None
    section_title: str | None = None
    primary_font: str = ""
    primary_size: float = 0.0
    is_bold: bool = False
    is_italic: bool = False
    color_hex: str = "#000000"
    spans: list[TextSpan] = Field(default_factory=list)


class TableCell(BaseModel):
    """Single cell within a parsed table."""

    row_idx: int
    col_idx: int
    text: str
    numeric_value: float | None = None
    unit_hint: str | None = None  # e.g. k€, M€, Md€, %, ETP
    is_percent: bool = False
    is_header: bool = False
    bbox: BoundingBox | None = None


class TableData(BaseModel):
    """Extracted table with header metadata, rows, and exact location."""

    table_id: str
    page_number: int
    bbox: BoundingBox
    title: str = ""
    unit_hint: str = ""  # e.g. "M€", "k€"
    section_id: str | None = None
    section_title: str | None = None
    headers: list[str] = Field(default_factory=list)
    rows: list[list[TableCell]] = Field(default_factory=list)


class CrossReference(BaseModel):
    """Detected internal reference ('cf. Note 14', 'voir page 42', 'section 3.2')."""

    ref_id: str
    page_number: int
    bbox: BoundingBox
    raw_text: str
    ref_type: Literal["note", "page", "section", "table", "annexe", "concordance"]
    target_identifier: str


class ConcordanceEntry(BaseModel):
    """Entry from AMF / URD concordance or summary table."""

    entry_id: str
    page_number: int
    bbox: BoundingBox
    label: str
    declared_pages: list[int] = Field(default_factory=list)
    declared_sections: list[str] = Field(default_factory=list)


class ChartFigure(BaseModel):
    """Detected visual chart/graphic area with optional rendered crop for Vision AI."""

    figure_id: str
    page_number: int
    bbox: BoundingBox
    title: str = ""
    nearby_text: str = ""
    extracted_labels: list[str] = Field(default_factory=list)
    image_path: str | None = None


class SectionNode(BaseModel):
    """Hierarchical section/chapter detected in the URD."""

    section_id: str
    level: int
    title: str
    normalized_title: str
    page_start: int
    page_end: int
    bbox: BoundingBox


class PageData(BaseModel):
    """All structured elements extracted from a single PDF page."""

    page_number: int
    width: float
    height: float
    raw_text: str
    blocks: list[TextBlock] = Field(default_factory=list)
    header_text: str = ""
    footer_text: str = ""
    displayed_page_number: int | None = None


class ParsedPDF(BaseModel):
    """Complete parsed representation of an enterprise URD PDF."""

    doc_id: str
    filename: str
    file_path: str
    page_count: int
    metadata: dict[str, str] = Field(default_factory=dict)
    pages: list[PageData] = Field(default_factory=list)
    sections: list[SectionNode] = Field(default_factory=list)
    tables: list[TableData] = Field(default_factory=list)
    cross_refs: list[CrossReference] = Field(default_factory=list)
    concordance_entries: list[ConcordanceEntry] = Field(default_factory=list)
    charts: list[ChartFigure] = Field(default_factory=list)
    esef_signals: list[dict[str, str | int]] = Field(default_factory=list)
