"""French & international financial number and unit parser for URD documents."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedNumber:
    raw: str
    value: float
    is_percent: bool = False
    unit: str | None = None  # "k€", "M€", "Md€", "€", "%", "ETP"
    scale_multiplier: float = 1.0  # Relative to € when monetary (1, 1e3, 1e6, 1e9)


UNIT_SCALE_MAP: dict[str, tuple[str, float]] = {
    "md€": ("Md€", 1_000_000_000.0),
    "mds€": ("Md€", 1_000_000_000.0),
    "milliard": ("Md€", 1_000_000_000.0),
    "milliards": ("Md€", 1_000_000_000.0),
    "milliard d'euros": ("Md€", 1_000_000_000.0),
    "milliards d'euros": ("Md€", 1_000_000_000.0),
    "milliard d’euros": ("Md€", 1_000_000_000.0),
    "milliards d’euros": ("Md€", 1_000_000_000.0),
    "bn€": ("Md€", 1_000_000_000.0),
    "m€": ("M€", 1_000_000.0),
    "meur": ("M€", 1_000_000.0),
    "millions d'euros": ("M€", 1_000_000.0),
    "million d'euros": ("M€", 1_000_000.0),
    "millions d’euros": ("M€", 1_000_000.0),
    "k€": ("k€", 1_000.0),
    "keur": ("k€", 1_000.0),
    "milliers d'euros": ("k€", 1_000.0),
    "milliers d’euros": ("k€", 1_000.0),
    "€": ("€", 1.0),
    "eur": ("€", 1.0),
    "etp": ("ETP", 1.0),
    "fte": ("ETP", 1.0),
}

_UNIT_RE = re.compile(
    r"(?i)(milliards?\s+d['’]euros?|millions?\s+d['’]euros?|milliers?\s+d['’]euros?|"
    r"mds?\s*€|m\s*€|k\s*€|meur|keur|bn€|€|eur|etp|fte)"
)

# Matches numbers like: "+4,2 %", "(1 234,5)", "-120.4", "12 450,00"
_NUM_TOKEN_RE = re.compile(
    r"(?<![A-Za-zÀ-ÿ0-9])"
    r"(\(?[+\-−]?\s*\d{1,3}(?:[\s\u00a0\u202f\.]\d{3})*(?:,\d+)?\)?|"
    r"\(?[+\-−]?\s*\d+(?:[.,]\d+)?\)?)"
    r"(\s*%|\s*(?:Md€|Mds€|M€|k€|MEUR|KEUR|€|EUR|ETP))?"
)


def detect_unit_in_text(text: str) -> tuple[str | None, float]:
    """Detect the dominant financial or headcount unit in a title/header/sentence."""
    if not text:
        return None, 1.0
    m = _UNIT_RE.search(text)
    if not m:
        return None, 1.0
    token = re.sub(r"\s+", "", m.group(1).lower())
    # Re-check phrase keys with spaces
    raw_lower = re.sub(r"\s+", " ", m.group(1).lower()).strip()
    if raw_lower in UNIT_SCALE_MAP:
        return UNIT_SCALE_MAP[raw_lower]
    if token in UNIT_SCALE_MAP:
        return UNIT_SCALE_MAP[token]
    return None, 1.0


def parse_financial_number(raw_text: str) -> ParsedNumber | None:
    """Parse a single table cell or numeric string into a float + unit metadata."""
    if not raw_text:
        return None
    cleaned = raw_text.strip().replace("\u00a0", " ").replace("\u202f", " ")
    if cleaned in {"-", "—", "–", "N/A", "NA", "n.s.", "ns", ""}:
        return None

    # Ignore pure dates or year labels if explicitly formatted as dates
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", cleaned):
        return None

    is_percent = "%" in cleaned
    unit, scale = detect_unit_in_text(cleaned)
    if is_percent and unit is None:
        unit = "%"

    # Extract numeric part
    num_part = _UNIT_RE.sub("", cleaned).replace("%", "").strip()
    if not num_part:
        return None

    is_negative = False
    if num_part.startswith("(") and num_part.endswith(")"):
        is_negative = True
        num_part = num_part[1:-1].strip()

    num_part = num_part.replace("−", "-").strip()
    if num_part.startswith("-"):
        is_negative = True
        num_part = num_part[1:].strip()
    elif num_part.startswith("+"):
        num_part = num_part[1:].strip()

    # Reject strings that still contain letters (e.g. "Note 14", "T1 2025")
    if re.search(r"[A-Za-zÀ-ÿ]", num_part):
        return None

    # Remove spaces used as thousand separators
    num_part = re.sub(r"\s+", "", num_part)
    if not num_part:
        return None

    # Handle decimal/thousand separators:
    # Case 1: both "." and "," -> e.g. "1.234,56" (EU) or "1,234.56" (US)
    if "," in num_part and "." in num_part:
        if num_part.rfind(",") > num_part.rfind("."):
            num_part = num_part.replace(".", "").replace(",", ".")
        else:
            num_part = num_part.replace(",", "")
    elif "," in num_part:
        # Check if multiple commas -> thousand separator, else decimal comma
        if num_part.count(",") > 1:
            num_part = num_part.replace(",", "")
        else:
            num_part = num_part.replace(",", ".")
    elif "." in num_part:
        # If formatted like "1.234.567" -> thousand separator
        parts = num_part.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) <= 3):
            # Ambiguous 1.234 -> in French URD, space is thousand sep, dot with 3 digits might be thousand sep if > 1 dot
            if len(parts) > 2:
                num_part = num_part.replace(".", "")

    try:
        val = float(num_part)
    except ValueError:
        return None

    if is_negative and val > 0:
        val = -val

    return ParsedNumber(
        raw=raw_text.strip(),
        value=val,
        is_percent=is_percent,
        unit=unit,
        scale_multiplier=scale,
    )


_DATE_STRIP_RE = re.compile(
    r"(?i)\b\d{1,2}\s+(?:janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|"
    r"septembre|octobre|novembre|d[eé]cembre)\s+20\d{2}\b|\b\d{2}[/\-]\d{2}[/\-]20\d{2}\b"
)


def extract_numbers_from_text(text: str) -> list[ParsedNumber]:
    """Extract all numbers (percentages, monetary figures, values) from narrative text."""
    results: list[ParsedNumber] = []
    if not text:
        return results

    scrubbed = _DATE_STRIP_RE.sub(" ", text)
    for match in _NUM_TOKEN_RE.finditer(scrubbed):
        token = match.group(0).strip()
        # Skip standalone 4-digit years like 2023, 2024, 2025, 2026 unless followed by unit/%
        unit_suffix = (match.group(2) or "").strip()
        if not unit_suffix and re.fullmatch(r"20[12]\d|19\d{2}", token):
            continue
        parsed = parse_financial_number(token)
        if parsed is not None:
            results.append(parsed)
    return results
