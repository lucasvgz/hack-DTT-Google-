"""Annotates V0 and V1 PDFs with color-coded highlights and comments at exact bboxes."""

from __future__ import annotations

from pathlib import Path
import pymupdf as fitz

from urd_verifier.models.findings import Finding, LocationRef, Severity

_SEVERITY_COLORS: dict[Severity, tuple[float, float, float]] = {
    Severity.CRITICAL: (0.92, 0.18, 0.18),
    Severity.MAJOR: (0.95, 0.55, 0.12),
    Severity.MINOR: (0.22, 0.52, 0.90),
    Severity.INFO: (0.18, 0.70, 0.58),
}


class PDFAnnotator:
    """Draws bounding-box highlights and popup annotations onto V0/V1 PDFs."""

    def annotate(
        self,
        source_pdf_path: str | Path,
        output_pdf_path: str | Path,
        findings: list[Finding],
        role: str,
    ) -> Path:
        src = Path(source_pdf_path)
        dst = Path(output_pdf_path)
        dst.parent.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(src))
        try:
            for f in findings:
                locs: list[LocationRef] = []
                if role == "v0" and f.v0_location is not None:
                    locs.append(f.v0_location)
                elif role == "v1" and f.v1_location is not None:
                    locs.append(f.v1_location)
                for extra in f.extra_locations:
                    if extra.doc_role == role:
                        locs.append(extra)

                color = _SEVERITY_COLORS.get(f.severity, (0.95, 0.55, 0.12))
                for loc in locs:
                    if not (1 <= loc.page_number <= len(doc)):
                        continue
                    page = doc[loc.page_number - 1]
                    rect = fitz.Rect(
                        loc.bbox.x0, loc.bbox.y0, loc.bbox.x1, loc.bbox.y1
                    )
                    if rect.is_empty or rect.width < 1 or rect.height < 1:
                        continue

                    annot = page.add_rect_annot(rect)
                    annot.set_colors(stroke=color, fill=color)
                    annot.set_opacity(0.22)
                    annot.set_border(width=1.5)
                    info_text = (
                        f"[{f.severity.value.upper()} | {f.diff_category.value} | {f.control_type.value}]\n"
                        f"{f.title}\n{f.description}"
                    )
                    if f.human_prompt:
                        info_text += f"\n\nAction Humaine: {f.human_prompt}"
                    annot.set_info(
                        title="URD Verifier Agent",
                        content=info_text[:1000],
                    )
                    annot.update()

            doc.save(str(dst), deflate=True)
        finally:
            doc.close()
        return dst
