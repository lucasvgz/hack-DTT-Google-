"""Base interface and shared localization helpers for URD verification checks."""

from __future__ import annotations

from abc import ABC, abstractmethod

from urd_verifier.models.document import BoundingBox, ParsedPDF, TableCell, TableData, TextBlock
from urd_verifier.models.findings import Finding, LocationRef


def make_block_loc(doc: ParsedPDF, blk: TextBlock, role: str) -> LocationRef:
    page = doc.pages[blk.page_number - 1]
    return LocationRef(
        doc_role=role,
        filename=doc.filename,
        page_number=blk.page_number,
        page_width=page.width,
        page_height=page.height,
        bbox=blk.bbox,
        section_title=blk.section_title,
        quoted_text=blk.text[:320],
    )


def make_table_loc(
    doc: ParsedPDF,
    tbl: TableData,
    role: str,
    cell: TableCell | None = None,
) -> LocationRef:
    page = doc.pages[tbl.page_number - 1]
    bbox = cell.bbox if cell and cell.bbox else tbl.bbox
    return LocationRef(
        doc_role=role,
        filename=doc.filename,
        page_number=tbl.page_number,
        page_width=page.width,
        page_height=page.height,
        bbox=bbox,
        section_title=tbl.section_title,
        table_id=tbl.table_id,
        cell_ref=f"row={cell.row_idx},col={cell.col_idx}" if cell else None,
        quoted_text=(cell.text if cell else tbl.title or tbl.table_id)[:280],
    )


def make_page_loc(
    doc: ParsedPDF, page_number: int, bbox: BoundingBox, role: str, quote: str
) -> LocationRef:
    page = doc.pages[page_number - 1]
    return LocationRef(
        doc_role=role,
        filename=doc.filename,
        page_number=page_number,
        page_width=page.width,
        page_height=page.height,
        bbox=bbox,
        quoted_text=quote[:300],
    )


class BaseCheckRunner(ABC):
    """Abstract base for deterministic, AI-assisted, and mandatory-HITL check suites."""

    @abstractmethod
    def run(
        self,
        v0: ParsedPDF,
        v1: ParsedPDF,
        urd_n_minus_1: ParsedPDF | None = None,
    ) -> list[Finding]:
        """Run checks and return localized Finding objects."""
        raise NotImplementedError
