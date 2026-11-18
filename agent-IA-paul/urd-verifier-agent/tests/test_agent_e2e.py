"""End-to-end tests covering all 15 URD control types, diff classification, bbox localization, and HITL."""

from pathlib import Path

from scripts.generate_sample_urds import generate_samples
from urd_verifier.agent import HITLManager, VerificationOrchestrator
from urd_verifier.config import VerifierSettings
from urd_verifier.models.findings import ControlType, DiffCategory, HITLStatus
from urd_verifier.models.session import HITLDecisionRequest, VersionOverrideRequest
from urd_verifier.storage import SessionStore


def test_full_e2e_verification_and_all_15_controls(tmp_path: Path):
    pdf_dir = tmp_path / "pdfs"
    data_dir = tmp_path / "sessions"
    paths = generate_samples(pdf_dir)

    settings = VerifierSettings(llm_provider="offline", data_dir=data_dir)
    store = SessionStore(data_dir)
    orch = VerificationOrchestrator(settings=settings, store=store)

    session = orch.create_session_from_paths(
        [paths["v1"], paths["v0"], paths["urd_n_minus_1"]]
    )
    session = orch.run_verification(session.session_id)

    assert session.status == "awaiting_human_review"
    assert session.version_detection is not None
    assert session.version_detection.v0_filename == "URD_2025_V0_Brouillon.pdf"
    assert session.version_detection.v1_filename == "URD_2025_V1_Amende.pdf"
    assert session.version_detection.urd_n_minus_1_filename == "URD_2024_Publie.pdf"

    # Verify diff categories (forme, contenu, chiffrage)
    diff_cats = {f.diff_category for f in session.findings}
    assert DiffCategory.FORME in diff_cats
    assert DiffCategory.CONTENU in diff_cats
    assert DiffCategory.CHIFFRAGE in diff_cats

    # Verify all 15 control types from the reference table are triggered on the sample URDs
    found_controls = {f.control_type for f in session.findings}
    expected_controls = {
        ControlType.ARITHMETIQUE_TABLEAUX,
        ControlType.CALCULS_VARIATIONS,
        ControlType.RENVOIS_CONCORDANCE,
        ControlType.COMPARATIF_N_1_BRUT,
        ControlType.HYGIENE_DOCUMENTAIRE,
        ControlType.CONFORMITE_ESEF,
        ControlType.CROSS_CHECKS_INTER_SECTIONS,
        ControlType.COHERENCE_TEXTE_TABLEAU,
        ControlType.UNITES_ECHELLES,
        ControlType.GRAPHIQUES_VS_TABLEAUX,
        ControlType.LIEN_FINANCE_CSRD,
        ControlType.VALIDATION_RETRAITEMENTS_N_1,
        ControlType.MATERIALITE_TOLERANCE,
        ControlType.EXHAUSTIVITE_RISQUES,
        ControlType.TON_NON_TROMPEUR,
    }
    missing = expected_controls - found_controls
    assert not missing, f"Controls manquants : {missing}"

    # Verify every finding has valid bounding boxes on V0 or V1
    for f in session.findings:
        loc = f.v1_location or f.v0_location
        assert loc is not None, f"Finding sans localisation : {f.title}"
        assert loc.page_number >= 1
        assert 0.0 <= loc.bbox.nx0 <= loc.bbox.nx1 <= 1.0
        assert 0.0 <= loc.bbox.ny0 <= loc.bbox.ny1 <= 1.0

    # Verify annotated PDFs were created
    assert session.annotated_v0_path and Path(session.annotated_v0_path).exists()
    assert session.annotated_v1_path and Path(session.annotated_v1_path).exists()

    # Verify HITL decision updates state and audit trail
    hitl = HITLManager()
    target = next(f for f in session.findings if f.requires_human_action)
    updated = hitl.apply_decision(
        session,
        target.finding_id,
        HITLDecisionRequest(
            auditor_name="Paul",
            new_status=HITLStatus.CONFIRMED_ERROR,
            comment="Confirmé après revue du dossier d'audit.",
            is_material=True,
        ),
    )
    assert updated.hitl_status == HITLStatus.CONFIRMED_ERROR
    assert updated.is_material is True
    assert len(updated.audit_trail) >= 2
    store.save_session(session)

    # Verify version override re-run works
    swapped = orch.override_versions_and_rerun(
        session.session_id,
        VersionOverrideRequest(
            auditor_name="Paul",
            v0_filename="URD_2025_V0_Brouillon.pdf",
            v1_filename="URD_2025_V1_Amende.pdf",
            urd_n_minus_1_filename="URD_2024_Publie.pdf",
        ),
    )
    assert swapped.version_detection is not None
    assert swapped.version_detection.confirmed_by_human is True
