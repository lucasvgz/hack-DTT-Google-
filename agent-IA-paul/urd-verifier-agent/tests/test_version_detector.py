"""Tests for automatic V0 vs V1 vs URD N-1 detection."""

from pathlib import Path

from scripts.generate_sample_urds import generate_samples
from urd_verifier.ingestion import PDFParser, VersionDetector


def test_detects_v0_v1_and_urd_n_minus_1(tmp_path: Path):
    paths = generate_samples(tmp_path)
    parser = PDFParser()
    # Intentionally pass in scrambled order!
    docs = [
        parser.parse(paths["v1"]),
        parser.parse(paths["urd_n_minus_1"]),
        parser.parse(paths["v0"]),
    ]
    res = VersionDetector().detect(docs)
    assert res.v0_filename == "URD_2025_V0_Brouillon.pdf"
    assert res.v1_filename == "URD_2025_V1_Amende.pdf"
    assert res.urd_n_minus_1_filename == "URD_2024_Publie.pdf"
    assert res.confidence >= 0.80
    assert res.needs_human_confirmation is False
