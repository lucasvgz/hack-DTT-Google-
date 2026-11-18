"""Adapter bridging urd-verifier-agent with the Tickmark UI contract (docs/API_CONTRACT.md)."""

from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pymupdf as fitz

from urd_verifier.models.findings import ControlType, DiffCategory, Finding, Severity
from urd_verifier.models.session import VerificationSession

_TOKEN_RE = re.compile(
    r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?(?![^\W_])"
    r"|\d+(?:[.,]\d+)?(?![^\W_])"
    r"|[^\W_]+"
    r"|\s+"
    r"|[^\s\w]"
)
_NUM_RE = re.compile(r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_SECTION_RE = re.compile(r"^\s*(\d+)\.\s+(.+)")

_CONTROL_LABELS: dict[ControlType, str] = {
    ControlType.ARITHMETIQUE_TABLEAUX: "Arithmétique des tableaux",
    ControlType.CALCULS_VARIATIONS: "Calculs de variations",
    ControlType.RENVOIS_CONCORDANCE: "Renvois & concordance",
    ControlType.COMPARATIF_N_1_BRUT: "Comparatif N-1 brut",
    ControlType.HYGIENE_DOCUMENTAIRE: "Hygiène documentaire",
    ControlType.CONFORMITE_ESEF: "Conformité ESEF",
    ControlType.CROSS_CHECKS_INTER_SECTIONS: "Incohérence inter-sections",
    ControlType.COHERENCE_TEXTE_TABLEAU: "Cohérence texte / tableau",
    ControlType.UNITES_ECHELLES: "Unités & échelles",
    ControlType.GRAPHIQUES_VS_TABLEAUX: "Graphiques vs tableaux",
    ControlType.LIEN_FINANCE_CSRD: "Lien Finance / CSRD",
    ControlType.VALIDATION_RETRAITEMENTS_N_1: "Retraitement N-1 (HITL)",
    ControlType.MATERIALITE_TOLERANCE: "Matérialité & tolérance",
    ControlType.EXHAUSTIVITE_RISQUES: "Risques & litiges (HITL)",
    ControlType.TON_NON_TROMPEUR: "Ton / IAP / Greenwashing",
    ControlType.DIFF_V0_V1: "Différence V0 vs V1",
    ControlType.CONTRADICTION_V0_V1: "Contradiction V0 vs V1",
}


def _deaccent(s: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn"
    ).lower()


def _levenshtein(a: str, b: str) -> int:
    dp = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev = dp[0]
        dp[0] = i
        for j, cb in enumerate(b, 1):
            tmp = dp[j]
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + (0 if ca == cb else 1))
            prev = tmp
    return dp[-1]


def _looks_like_spelling(before: str, after: str) -> bool:
    wa = _WORD_RE.findall(before)
    wb = _WORD_RE.findall(after)
    if not wa or len(wa) != len(wb):
        return False
    for w, x in zip(wa, wb):
        if w == x or _deaccent(w) == _deaccent(x):
            continue
        dist = _levenshtein(w.lower(), x.lower())
        if dist > 2 or dist / max(len(w), len(x)) > 0.34:
            return False
    return True


def extract_tickmark_text(pdf_path: str | Path) -> tuple[str, int, list[tuple[int, int]]]:
    """Extract clean line/page-separated text (pages joined by '\\f') matching Tickmark's viewer."""
    text, pages, offsets, _layout = extract_tickmark_document(pdf_path)
    return text, pages, offsets


def extract_tickmark_document(
    pdf_path: str | Path,
) -> tuple[str, int, list[tuple[int, int]], dict[str, Any]]:
    """Same as extract_tickmark_text, plus the Tickmark position map (`layout`).

    layout = {"pages": [{"w", "h", "f": [[start, end, x, y, width, size], ...]}]}
    with start/end offsets in the full text and x/y the span baseline in PDF
    points (origin bottom-left), as produced by the front's js/pdf-extract.js.
    """
    doc = fitz.open(str(pdf_path))
    pages_text: list[str] = []
    layout_pages: list[dict[str, Any]] = []
    try:
        for page in doc:
            page_h = float(page.rect.height)
            layout_page: dict[str, Any] = {
                "w": round(float(page.rect.width), 1),
                "h": round(page_h, 1),
                "f": [],
            }
            layout_pages.append(layout_page)
            local_frags: list[tuple[int, int, float, float, float, float]] = []
            d = page.get_text("dict")
            frags: list[tuple[float, float, float, float, str, float, float]] = []
            for blk in d.get("blocks", []):
                if blk.get("type") != 0:
                    continue
                for line in blk.get("lines", []):
                    for sp in line.get("spans", []):
                        txt = sp.get("text", "")
                        if not txt:
                            continue
                        x0, y0, x1, y1 = sp["bbox"]
                        size = float(sp.get("size", 10.0))
                        ox, oy = sp.get("origin", (x0, y1))
                        frags.append((y0, x0, x1 - x0, max(y1 - y0, size), txt, page_h - float(oy), size))

            if not frags:
                pages_text.append("")
                continue

            # Group spans into visual lines (y0 ascending = top-to-bottom)
            frags.sort(key=lambda f: (f[0], f[1]))
            lines: list[dict[str, Any]] = []
            for y0, x0, w, h, txt, base_y, size in frags:
                item = (x0, w, h, txt, base_y, size)
                if lines and abs(lines[-1]["y"] - y0) <= h * 0.45:
                    lines[-1]["items"].append(item)
                else:
                    lines.append({"y": y0, "h": h, "items": [item]})

            gaps = [lines[i]["y"] - lines[i - 1]["y"] for i in range(1, len(lines))]
            pos_gaps = sorted(g for g in gaps if g > 0.5)
            median = pos_gaps[len(pos_gaps) // 2] if pos_gaps else 0.0

            out_parts: list[str] = []
            page_len = 0
            for idx, ln in enumerate(lines):
                ln["items"].sort(key=lambda it: it[0])
                line_str = ""
                line_frags: list[tuple[int, int, float, float, float, float]] = []
                for j, (x0, w, h, txt, base_y, size) in enumerate(ln["items"]):
                    if j > 0:
                        px0, pw = ln["items"][j - 1][:2]
                        gap_x = x0 - (px0 + pw)
                        if gap_x > h * 0.18 and not line_str.endswith((" ", "\t")) and not txt.startswith((" ", "\t")):
                            line_str += " "
                    line_frags.append((len(line_str), len(line_str) + len(txt), x0, base_y, w, size))
                    line_str += txt

                if idx > 0:
                    gap_y = ln["y"] - lines[idx - 1]["y"]
                    blank = max(0, round(gap_y / median) - 1) if median > 0 else 0
                    sep = "\n" + "\n" * min(blank, 3)
                    out_parts.append(sep)
                    page_len += len(sep)
                for fs, fe, x, y, w, size in line_frags:
                    local_frags.append((page_len + fs, page_len + fe, x, y, w, size))
                out_parts.append(line_str)
                page_len += len(line_str)

            pages_text.append("".join(out_parts))
            layout_page["_local"] = local_frags
    finally:
        doc.close()

    full_text = "\f".join(pages_text)
    offsets: list[tuple[int, int]] = []
    cursor = 0
    for i, pt in enumerate(pages_text):
        start = cursor
        end = start + len(pt)
        offsets.append((start, end))
        lp = layout_pages[i]
        lp["f"] = [
            [start + fs, start + fe, round(x, 1), round(y, 1), round(w, 1), round(size, 1)]
            for fs, fe, x, y, w, size in lp.pop("_local", [])
        ]
        cursor = end + (1 if i < len(pages_text) - 1 else 0)
    return full_text, len(pages_text), offsets, {"pages": layout_pages}


def _split_lines_with_offsets(text: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    start = 0
    for i, ch in enumerate(text):
        if ch in ("\n", "\f"):
            out.append((text[start : i + 1], start))
            start = i + 1
    if start < len(text):
        out.append((text[start:], start))
    return out


def _tokenize_with_offsets(text: str, base: int) -> list[tuple[str, int]]:
    return [(m.group(0), base + m.start()) for m in _TOKEN_RE.finditer(text)]


def _page_at(text: str, offset: int) -> int:
    return text[: min(offset, len(text))].count("\f") + 1


def _section_at(text: str, offset: int) -> str:
    head = text[: min(offset, len(text))]
    for line in reversed(re.split(r"[\n\f]", head)):
        m = _SECTION_RE.match(line)
        if m:
            title = re.sub(r"\s*\(.*$", "", m.group(2)).strip()
            if len(title) > 38:
                title = title[:37] + "…"
            return f"§{m.group(1)} {title}"
    return "En-tête"


def _context_at(text: str, start: int, end: int) -> str:
    a = max(0, start - 45)
    b = min(len(text), end + 45)
    ctx = re.sub(r"[\n\f]+", " ", text[a:b])
    return ("…" if a > 0 else "") + ctx + ("…" if b < len(text) else "")


def categorize_tickmark_hunk(before: str, after: str) -> dict[str, Any]:
    """Objective 6-rule categorization matching docs/API_CONTRACT.md."""
    strip_ws = lambda s: re.sub(r"\s+", "", s)
    strip_punct = lambda s: re.sub(r"[^\w]", "", s, flags=re.UNICODE)

    if strip_ws(before) == strip_ws(after):
        nl_b, nl_a = before.count("\n"), after.count("\n")
        lb = nl_b != nl_a
        vis = lambda s: s.replace("\n", "↵").replace("\f", "⇟").replace(" ", "·")
        return {
            "category": "mise_en_forme",
            "severity": "info",
            "subtype": "Saut de ligne" if lb else "Espacement",
            "rationale": (
                f"Seuls les retours à la ligne diffèrent ({nl_b} → {nl_a}). Aucun caractère imprimable modifié — souvent dû à une remise en page."
                if lb
                else f"Seuls les espaces diffèrent (« {vis(before)} » → « {vis(after)} »). Aucun caractère imprimable modifié."
            ),
            "confidence": 0.99,
        }

    if strip_punct(before) == strip_punct(after):
        return {
            "category": "ponctuation",
            "severity": "faible",
            "subtype": "Ponctuation",
            "rationale": "Les lettres et chiffres sont identiques ; seule la ponctuation (virgule, point, tiret…) change.",
            "confidence": 0.97,
        }

    if not before.strip() or not after.strip():
        added = not before.strip()
        target = after if added else before
        has_num = bool(re.search(r"\d", target))
        return {
            "category": "ajout_suppression",
            "severity": "elevee" if has_num else "moyenne",
            "subtype": "Contenu ajouté" if added else "Contenu supprimé",
            "rationale": (
                f"Texte {'présent uniquement dans la nouvelle version' if added else 'présent uniquement dans la version précédente'}."
                + (" Contient des données chiffrées : à rapprocher des états financiers." if has_num else "")
            ),
            "confidence": 0.95,
        }

    digits_b = "|".join(_NUM_RE.findall(before))
    digits_a = "|".join(_NUM_RE.findall(after))
    if re.search(r"\d", before + after) and digits_b != digits_a:
        return {
            "category": "chiffres",
            "severity": "elevee",
            "subtype": "Montant / donnée chiffrée",
            "rationale": f"La donnée chiffrée change ({digits_b.replace('|', ' ; ') or '—'} → {digits_a.replace('|', ' ; ') or '—'}). À rapprocher de la balance / des états financiers.",
            "confidence": 0.98,
        }

    if _looks_like_spelling(before, after):
        return {
            "category": "orthographe",
            "severity": "faible",
            "subtype": "Correction orthographique",
            "rationale": "Mots de même structure à 1-2 caractères près (lettre, accent ou casse) : correction ou faute de frappe probable.",
            "confidence": 0.86,
        }

    return {
        "category": "formulation",
        "severity": "moyenne",
        "subtype": "Reformulation",
        "rationale": "Des mots différents sont utilisés. Vérifier que le sens et la portée de l'information sont inchangés.",
        "confidence": 0.82,
    }


def _compute_text_hunks(before_text: str, after_text: str) -> list[dict[str, Any]]:
    la = _split_lines_with_offsets(before_text)
    lb = _split_lines_with_offsets(after_text)
    line_matcher = SequenceMatcher(None, [x[0] for x in la], [x[0] for x in lb], autojunk=False)

    blocks: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in line_matcher.get_opcodes():
        if tag == "equal":
            continue
        a_start = la[i1][1] if i1 < len(la) else len(before_text)
        b_start = lb[j1][1] if j1 < len(lb) else len(after_text)
        a_str = "".join(la[k][0] for k in range(i1, i2))
        b_str = "".join(lb[k][0] for k in range(j1, j2))
        blocks.append({"a_start": a_start, "b_start": b_start, "a_str": a_str, "b_str": b_str})

    raw_hunks: list[list[int]] = []  # [a0, a1, b0, b1]
    for blk in blocks:
        ta = _tokenize_with_offsets(blk["a_str"], blk["a_start"])
        tb = _tokenize_with_offsets(blk["b_str"], blk["b_start"])
        tok_matcher = SequenceMatcher(None, [t[0] for t in ta], [t[0] for t in tb], autojunk=False)
        for tag, i1, i2, j1, j2 in tok_matcher.get_opcodes():
            if tag == "equal":
                continue
            a0 = ta[i1][1] if i1 < len(ta) else (ta[i1 - 1][1] + len(ta[i1 - 1][0]) if i1 > 0 and ta else blk["a_start"])
            a1 = (ta[i2 - 1][1] + len(ta[i2 - 1][0])) if i2 > i1 else a0
            b0 = tb[j1][1] if j1 < len(tb) else (tb[j1 - 1][1] + len(tb[j1 - 1][0]) if j1 > 0 and tb else blk["b_start"])
            b1 = (tb[j2 - 1][1] + len(tb[j2 - 1][0])) if j2 > j1 else b0
            raw_hunks.append([a0, a1, b0, b1])

    # Merge two text hunks separated by a single identical space
    merged: list[list[int]] = []
    for h in raw_hunks:
        if merged:
            p = merged[-1]
            gap_a = before_text[p[1] : h[0]]
            gap_b = after_text[p[3] : h[2]]
            p_txt = bool((before_text[p[0] : p[1]] + after_text[p[2] : p[3]]).strip())
            h_txt = bool((before_text[h[0] : h[1]] + after_text[h[2] : h[3]]).strip())
            if p_txt and h_txt and gap_a == gap_b == " ":
                p[1] = h[1]
                p[3] = h[3]
                continue
        merged.append(h)

    # Trim common leading/trailing whitespace
    for h in merged:
        while (
            h[1] > h[0]
            and h[3] > h[2]
            and before_text[h[1] - 1].isspace()
            and before_text[h[1] - 1] == after_text[h[3] - 1]
            and (before_text[h[0] : h[1] - 1] + after_text[h[2] : h[3] - 1]).strip()
        ):
            h[1] -= 1
            h[3] -= 1
        while (
            h[1] > h[0]
            and h[3] > h[2]
            and before_text[h[0]].isspace()
            and before_text[h[0]] == after_text[h[2]]
            and (before_text[h[0] + 1 : h[1]] + after_text[h[2] + 1 : h[3]]).strip()
        ):
            h[0] += 1
            h[2] += 1

    out: list[dict[str, Any]] = []
    for a0, a1, b0, b1 in merged:
        b_slice = before_text[a0:a1]
        a_slice = after_text[b0:b1]
        cat = categorize_tickmark_hunk(b_slice, a_slice)
        out.append(
            {
                **cat,
                "before": b_slice,
                "after": a_slice,
                "beforeRange": [a0, a1],
                "afterRange": [b0, b1],
                "page": _page_at(after_text, b0),
                "section": _section_at(after_text, b0),
                "context": _context_at(after_text, b0, b1),
            }
        )
    return out


def _ranges_overlap(r1: tuple[int, int], r2: tuple[int, int]) -> bool:
    s1, e1 = r1
    s2, e2 = r2
    if s1 == e1 and s2 == e2:
        return s1 == s2
    if s1 == e1:
        return s2 <= s1 < e2
    if s2 == e2:
        return s1 <= s2 < e1
    return max(s1, s2) < min(e1, e2)


def _match_finding_to_hunk(hunk: dict[str, Any], findings: list[Finding]) -> Finding | None:
    page = hunk["page"]
    b_val = hunk["before"].strip().lower()
    a_val = hunk["after"].strip().lower()
    for f in findings:
        loc = f.v1_location or f.v0_location
        if not loc or loc.page_number != page:
            continue
        if f.control_type == ControlType.DIFF_V0_V1 and f.diff_category != DiffCategory.FORME:
            # Prefer specialized controls (retraitement, risque, variation, etc.)
            continue
        haystack = " ".join(
            filter(None, [f.v0_value, f.v1_value, loc.quoted_text, f.description])
        ).lower()
        if (a_val and len(a_val) >= 2 and a_val in haystack) or (
            b_val and len(b_val) >= 2 and b_val in haystack
        ):
            return f
    return None


def _find_snippet_on_page(
    text: str, page_offsets: list[tuple[int, int]], page: int, snippet: str
) -> tuple[int, int] | None:
    if not snippet or not (1 <= page <= len(page_offsets)):
        return None
    p_start, p_end = page_offsets[page - 1]
    page_slice = text[p_start:p_end]
    clean = " ".join(snippet.split()).strip()
    if not clean:
        return None
    idx = page_slice.find(clean)
    if idx >= 0:
        return p_start + idx, p_start + idx + len(clean)
    # Try first 40 chars or numeric token inside snippet
    short = clean[:40].strip()
    if len(short) >= 6:
        idx = page_slice.find(short)
        if idx >= 0:
            return p_start + idx, p_start + idx + len(short)
    return None


def build_tickmark_response(
    session: VerificationSession,
    before_pdf_path: str | Path,
    after_pdf_path: str | Path,
    llm_provider: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build Tickmark API payload + diff_id->finding_id mapping from a VerificationSession."""
    before_text, before_pages, before_offsets, before_layout = extract_tickmark_document(before_pdf_path)
    after_text, after_pages, after_offsets, after_layout = extract_tickmark_document(after_pdf_path)

    hunks = _compute_text_hunks(before_text, after_text)
    used_findings: set[str] = set()

    # 1. Enrich text hunks with specialized agent findings
    for h in hunks:
        matched = _match_finding_to_hunk(h, session.findings)
        if matched:
            used_findings.add(matched.finding_id)
            ctrl_lbl = _CONTROL_LABELS.get(matched.control_type, matched.control_type.value)
            h["subtype"] = f"{h['subtype']} · {ctrl_lbl}"
            extra_note = matched.human_prompt or matched.ai_rationale or matched.description
            if extra_note and extra_note not in h["rationale"]:
                h["rationale"] = f"{h['rationale']} | Agent URD ({ctrl_lbl}) : {extra_note}"
            if matched.severity == Severity.CRITICAL:
                h["severity"] = "elevee"
            h["findingId"] = matched.finding_id
            h["controlType"] = matched.control_type.value
            h["automationLevel"] = matched.automation_level.value

    # 2. Surface internal URD agent findings (cross-checks, math, risks, tone, ESEF, typographic form)
    # that aren't already covered by a diff hunk, without ever overlapping existing ranges!
    existing_after_ranges = [tuple(h["afterRange"]) for h in hunks]
    existing_before_ranges = [tuple(h["beforeRange"]) for h in hunks]

    for f in session.findings:
        if f.finding_id in used_findings:
            continue
        if f.control_type == ControlType.DIFF_V0_V1 and f.diff_category != DiffCategory.FORME:
            continue
        if f.severity not in {Severity.CRITICAL, Severity.MAJOR} and f.diff_category != DiffCategory.FORME:
            continue
        loc = f.v1_location
        if loc is None:
            continue

        # Locate exact span in after_text
        candidate_snippet = (f.v1_value or loc.quoted_text or "").strip()
        span_a = _find_snippet_on_page(after_text, after_offsets, loc.page_number, candidate_snippet)
        if span_a is None and loc.quoted_text:
            span_a = _find_snippet_on_page(after_text, after_offsets, loc.page_number, loc.quoted_text)
        if span_a is None:
            continue

        if any(_ranges_overlap(span_a, r) for r in existing_after_ranges):
            continue

        # Pick a non-overlapping anchor in before_text on the matching page
        p_idx = min(loc.page_number, len(before_offsets)) - 1
        anchor_b = before_offsets[p_idx][0] if p_idx >= 0 else 0
        while any(_ranges_overlap((anchor_b, anchor_b), r) for r in existing_before_ranges):
            anchor_b += 1
        if anchor_b > len(before_text):
            anchor_b = len(before_text)

        ctrl_lbl = _CONTROL_LABELS.get(f.control_type, f.control_type.value)
        cat = (
            "mise_en_forme"
            if f.diff_category == DiffCategory.FORME
            else ("chiffres" if f.diff_category == DiffCategory.CHIFFRAGE else "formulation")
        )
        sev = (
            "elevee"
            if f.severity == Severity.CRITICAL
            else ("moyenne" if f.severity == Severity.MAJOR else "info")
        )
        rationale_parts = [f.description]
        if f.human_prompt:
            rationale_parts.append(f"Point HITL : {f.human_prompt}")

        existing_after_ranges.append(span_a)
        existing_before_ranges.append((anchor_b, anchor_b))
        used_findings.add(f.finding_id)

        hunks.append(
            {
                "category": cat,
                "severity": sev,
                "subtype": f"Agent URD · {ctrl_lbl}",
                "before": "",
                "after": after_text[span_a[0] : span_a[1]],
                "beforeRange": [anchor_b, anchor_b],
                "afterRange": [span_a[0], span_a[1]],
                "page": loc.page_number,
                "section": loc.section_title or _section_at(after_text, span_a[0]),
                "context": _context_at(after_text, span_a[0], span_a[1]),
                "rationale": " — ".join(rationale_parts),
                "confidence": f.confidence,
                "findingId": f.finding_id,
                "controlType": f.control_type.value,
                "automationLevel": f.automation_level.value,
            }
        )

    # Sort deterministically in document order
    hunks.sort(key=lambda h: (h["afterRange"][0], h["beforeRange"][0]))

    # Assign sequential IDs (d001, d002, ...) and record finding_id links
    diff_to_finding: dict[str, str] = {}
    for idx, h in enumerate(hunks, 1):
        did = f"d{idx:03d}"
        h["id"] = did
        fid = h.pop("findingId", None)
        if fid:
            diff_to_finding[did] = fid

    engine_name = f"urd-verifier-agent+{llm_provider}"
    payload = {
        "id": session.session_id,
        "engine": engine_name,
        "documents": {
            "before": {"text": before_text, "pageCount": before_pages, "layout": before_layout},
            "after": {"text": after_text, "pageCount": after_pages, "layout": after_layout},
        },
        "differences": hunks,
        "agentSummary": session.summary.model_dump(),
        "versionDetection": (
            session.version_detection.model_dump() if session.version_detection else None
        ),
    }
    return payload, diff_to_finding
