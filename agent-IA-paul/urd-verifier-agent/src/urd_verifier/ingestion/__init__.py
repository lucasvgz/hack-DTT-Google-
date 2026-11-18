"""PDF ingestion, financial number parsing, and V0/V1 version identification."""

from .number_parser import ParsedNumber, extract_numbers_from_text, parse_financial_number, detect_unit_in_text
from .pdf_parser import PDFParser
from .version_detector import VersionDetector

__all__ = [
    "PDFParser",
    "ParsedNumber",
    "VersionDetector",
    "detect_unit_in_text",
    "extract_numbers_from_text",
    "parse_financial_number",
]
