"""Aligns text blocks and tables between V0 and V1 even across shifted pages."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Generic, TypeVar

from urd_verifier.models.document import ParsedPDF, TableData, TextBlock

T = TypeVar("T")


@dataclass
class AlignedPair(Generic[T]):
    v0_item: T | None
    v1_item: T | None
    similarity: float = 1.0


def _norm_text(t: str) -> str:
    return " ".join(t.lower().split())


def _table_signature(tbl: TableData) -> str:
    row_labels = [
        _norm_text(r[0].text) for r in tbl.rows[1:8] if r and r[0].text.strip()
    ]
    return f"{_norm_text(tbl.title)} | {' '.join(_norm_text(h) for h in tbl.headers)} | {' '.join(row_labels)}"


class DocumentAligner:
    """Aligns blocks and tables between V0 and V1 using content + structural fingerprints."""

    def align_blocks(
        self, v0: ParsedPDF, v1: ParsedPDF
    ) -> list[AlignedPair[TextBlock]]:
        v0_blocks = [
            b for p in v0.pages for b in p.blocks if b.block_type not in {"header", "footer"}
        ]
        v1_blocks = [
            b for p in v1.pages for b in p.blocks if b.block_type not in {"header", "footer"}
        ]

        v0_keys = [_norm_text(b.text)[:160] for b in v0_blocks]
        v1_keys = [_norm_text(b.text)[:160] for b in v1_blocks]

        matcher = SequenceMatcher(None, v0_keys, v1_keys, autojunk=False)
        pairs: list[AlignedPair[TextBlock]] = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    pairs.append(
                        AlignedPair(v0_item=v0_blocks[i1 + k], v1_item=v1_blocks[j1 + k], similarity=1.0)
                    )
            elif tag == "replace":
                # Sub-match replaced slice by fuzzy similarity so modified paragraphs pair up
                sub_v0 = v0_blocks[i1:i2]
                sub_v1 = v1_blocks[j1:j2]
                used_v1: set[int] = set()
                for b0 in sub_v0:
                    best_idx = -1
                    best_sim = 0.0
                    t0 = _norm_text(b0.text)
                    for idx1, b1 in enumerate(sub_v1):
                        if idx1 in used_v1:
                            continue
                        t1 = _norm_text(b1.text)
                        sim = SequenceMatcher(None, t0, t1).ratio()
                        # Boost if same section or same block type
                        if b0.block_type == b1.block_type:
                            sim = min(1.0, sim + 0.05)
                        if sim > best_sim:
                            best_sim = sim
                            best_idx = idx1
                    if best_idx >= 0 and best_sim >= 0.42:
                        used_v1.add(best_idx)
                        pairs.append(
                            AlignedPair(v0_item=b0, v1_item=sub_v1[best_idx], similarity=best_sim)
                        )
                    else:
                        pairs.append(AlignedPair(v0_item=b0, v1_item=None, similarity=0.0))
                for idx1, b1 in enumerate(sub_v1):
                    if idx1 not in used_v1:
                        pairs.append(AlignedPair(v0_item=None, v1_item=b1, similarity=0.0))
            elif tag == "delete":
                for b0 in v0_blocks[i1:i2]:
                    pairs.append(AlignedPair(v0_item=b0, v1_item=None, similarity=0.0))
            elif tag == "insert":
                for b1 in v1_blocks[j1:j2]:
                    pairs.append(AlignedPair(v0_item=None, v1_item=b1, similarity=0.0))

        return pairs

    def align_headers_footers(
        self, v0: ParsedPDF, v1: ParsedPDF
    ) -> list[tuple[int, str, str]]:
        """Compare page headers/footers for metadata/hygiene changes."""
        diffs: list[tuple[int, str, str]] = []
        min_pages = min(len(v0.pages), len(v1.pages))
        for i in range(min_pages):
            p0, p1 = v0.pages[i], v1.pages[i]
            # Strip page number before comparing header/footer template
            h0 = " ".join(p0.header_text.split())
            h1 = " ".join(p1.header_text.split())
            if h0 != h1 and (h0 or h1):
                diffs.append((i + 1, h0, h1))
        return diffs

    def align_tables(
        self, v0: ParsedPDF, v1: ParsedPDF
    ) -> list[AlignedPair[TableData]]:
        used_v1: set[int] = set()
        pairs: list[AlignedPair[TableData]] = []

        sigs_v0 = [_table_signature(t) for t in v0.tables]
        sigs_v1 = [_table_signature(t) for t in v1.tables]

        for i0, t0 in enumerate(v0.tables):
            best_idx = -1
            best_sim = 0.0
            for i1, t1 in enumerate(v1.tables):
                if i1 in used_v1:
                    continue
                sim = SequenceMatcher(None, sigs_v0[i0], sigs_v1[i1]).ratio()
                if t0.title and t1.title and _norm_text(t0.title) == _norm_text(t1.title):
                    sim = max(sim, 0.90)
                if sim > best_sim:
                    best_sim = sim
                    best_idx = i1
            if best_idx >= 0 and best_sim >= 0.48:
                used_v1.add(best_idx)
                pairs.append(
                    AlignedPair(v0_item=t0, v1_item=v1.tables[best_idx], similarity=best_sim)
                )
            else:
                pairs.append(AlignedPair(v0_item=t0, v1_item=None, similarity=0.0))

        for i1, t1 in enumerate(v1.tables):
            if i1 not in used_v1:
                pairs.append(AlignedPair(v0_item=None, v1_item=t1, similarity=0.0))

        return pairs
