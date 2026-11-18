"""Edge-case tests for shifted pages, ambiguous version detection, and batch HITL completion."""

from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

from urd_verifier.agent import HITLManager, VerificationOrchestrator
from urd_verifier.config import VerifierSettings
from urd_verifier.models.findings import DiffCategory, HITLStatus
from urd_verifier.models.session import HITLDecisionRequest
from urd_verifier.storage import SessionStore


def _make_pdf(path: Path, pages_paragraphs: list[list[str]]) -> Path:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=A4)
    story = []
    for p_idx, paras in enumerate(pages_paragraphs):
        if p_idx > 0:
            story.append(PageBreak())
        for text in paras:
            story.append(Paragraph(text, styles["BodyText"]))
    doc.build(story)
    return path


def test_shifted_pages_and_ambiguous_filenames(tmp_path: Path):
    # Filenames give ZERO hint (doc_alpha.pdf vs doc_beta.pdf), but internal dates do!
    p_v0 = _make_pdf(
        tmp_path / "doc_alpha.pdf",
        [
            ["Rapport Annuel 2025", "10 mars 2026"],
            ["Chapitre 1 : Activité stable avec un chiffre d'affaires de 500 M€."],
        ],
    )
    p_v1 = _make_pdf(
        tmp_path / "doc_beta.pdf",
        [
            ["Rapport Annuel 2025", "25 mars 2026"],
            ["Nouvel avant-propos du Directeur Général inséré en V1."],
            ["Chapitre 1 : Activité stable avec un chiffre d'affaires de 520 M€."],
        ],
    )

    data_dir = tmp_path / "sessions"
    orch = VerificationOrchestrator(
        settings=VerifierSettings(llm_provider="offline", data_dir=data_dir),
        store=SessionStore(data_dir),
    )
    session = orch.create_session_from_paths([p_v1, p_v0])
    session = orch.run_verification(session.session_id)

    assert session.version_detection is not None
    assert session.version_detection.v0_filename == "doc_alpha.pdf"
    assert session.version_detection.v1_filename == "doc_beta.pdf"

    # Verify shifted page alignment paired Chapitre 1 (V0 p.2 -> V1 p.3) as CHIFFRAGE diff
    chiffrage_diffs = [
        f for f in session.findings if f.diff_category == DiffCategory.CHIFFRAGE
    ]
    assert len(chiffrage_diffs) == 1
    assert chiffrage_diffs[0].v0_location is not None
    assert chiffrage_diffs[0].v1_location is not None
    assert chiffrage_diffs[0].v0_location.page_number == 2
    assert chiffrage_diffs[0].v1_location.page_number == 3
    assert chiffrage_diffs[0].numeric_delta == 20.0

    # Batch resolve all findings -> session transitions to completed
    hitl = HITLManager()
    all_ids = [f.finding_id for f in session.findings]
    updated_count = hitl.apply_batch_decision(
        session,
        all_ids,
        HITLDecisionRequest(
            auditor_name="Claire",
            new_status=HITLStatus.ACCEPTED_CHANGE,
            comment="Tout est vérifié.",
        ),
    )
    assert updated_count == len(all_ids)
    assert session.status == "completed"
    assert session.summary.overall_readiness == "ready"
