"""REST endpoints for UI integration (PDF upload, diff/control findings, PDF serving, HITL)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from urd_verifier.agent import HITLManager, VerificationOrchestrator
from urd_verifier.api.tickmark_adapter import build_tickmark_response
from urd_verifier.config import get_settings
from urd_verifier.models.findings import (
    AutomationLevel,
    ControlType,
    DiffCategory,
    Finding,
    HITLStatus,
    Severity,
)
from urd_verifier.models.session import (
    HITLDecisionRequest,
    VerificationSession,
    VersionOverrideRequest,
)
from urd_verifier.storage import SessionStore

router = APIRouter(prefix="/api/v1", tags=["URD Verifier"])


def _get_orchestrator() -> VerificationOrchestrator:
    settings = get_settings()
    store = SessionStore(
        settings.data_dir,
        gcs_bucket=settings.gcs_bucket,
        gcs_prefix=settings.gcs_prefix,
    )
    return VerificationOrchestrator(settings=settings, store=store)


class LocalVerifyRequest(BaseModel):
    file_paths: list[str]
    v0_filename: str | None = None
    v1_filename: str | None = None
    urd_n_minus_1_filename: str | None = None


class BatchReviewRequest(BaseModel):
    finding_ids: list[str]
    decision: HITLDecisionRequest


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "llm_provider": settings.resolve_active_provider(),
        "storage": "gcs" if settings.gcs_bucket else "local",
        "cloud_run": str(settings.is_cloud_run).lower(),
    }


@router.get("/taxonomy")
def get_taxonomy() -> dict:
    """Returns all diff categories, 15 control types, automation levels, and HITL statuses for UI filters."""
    control_catalog = [
        {"id": ControlType.ARITHMETIQUE_TABLEAUX.value, "label": "Arithmétique des tableaux", "automation": "100 % Automatisable"},
        {"id": ControlType.CALCULS_VARIATIONS.value, "label": "Calculs de variations", "automation": "100 % Automatisable"},
        {"id": ControlType.RENVOIS_CONCORDANCE.value, "label": "Renvois & tables de concordance", "automation": "100 % Automatisable"},
        {"id": ControlType.COMPARATIF_N_1_BRUT.value, "label": "Comparatif N-1 brut", "automation": "100 % Automatisable"},
        {"id": ControlType.HYGIENE_DOCUMENTAIRE.value, "label": "Hygiène documentaire", "automation": "100 % Automatisable"},
        {"id": ControlType.CONFORMITE_ESEF.value, "label": "Conformité technique ESEF", "automation": "100 % Automatisable"},
        {"id": ControlType.CROSS_CHECKS_INTER_SECTIONS.value, "label": "Cross-checks inter-sections", "automation": "Semi-automatisable (IA + Humain)"},
        {"id": ControlType.COHERENCE_TEXTE_TABLEAU.value, "label": "Cohérence texte vs tableau", "automation": "Semi-automatisable (IA + Humain)"},
        {"id": ControlType.UNITES_ECHELLES.value, "label": "Unités & échelles", "automation": "Semi-automatisable (IA + Humain)"},
        {"id": ControlType.GRAPHIQUES_VS_TABLEAUX.value, "label": "Graphiques vs tableaux", "automation": "Semi-automatisable (IA + Humain)"},
        {"id": ControlType.LIEN_FINANCE_CSRD.value, "label": "Lien Finance / Durabilité (CSRD)", "automation": "Semi-automatisable (IA + Humain)"},
        {"id": ControlType.VALIDATION_RETRAITEMENTS_N_1.value, "label": "Validation des retraitements N-1", "automation": "Human Check obligatoire"},
        {"id": ControlType.MATERIALITE_TOLERANCE.value, "label": "Matérialité & tolérance", "automation": "Human Check obligatoire"},
        {"id": ControlType.EXHAUSTIVITE_RISQUES.value, "label": "Exhaustivité & fidélité des risques", "automation": "Human Check obligatoire"},
        {"id": ControlType.TON_NON_TROMPEUR.value, "label": "Ton & caractère non trompeur", "automation": "Human Check obligatoire"},
        {"id": ControlType.DIFF_V0_V1.value, "label": "Différence V0 vs V1", "automation": "Automatisé / HITL"},
    ]
    return {
        "diff_categories": [c.value for c in DiffCategory],
        "control_types": control_catalog,
        "automation_levels": [a.value for a in AutomationLevel],
        "severities": [s.value for s in Severity],
        "hitl_statuses": [h.value for h in HITLStatus],
    }


@router.post("/sessions/verify", response_model=VerificationSession)
async def upload_and_verify(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    run_async: bool = Query(default=False),
) -> VerificationSession:
    """Upload 2+ URD PDFs from UI, detect V0/V1, and execute full verification."""
    if len(files) < 2:
        raise HTTPException(
            status_code=400, detail="Veuillez fournir au moins 2 fichiers PDF (V0 et V1)."
        )

    orch = _get_orchestrator()
    session = orch.create_session_empty()
    for uf in files:
        if not uf.filename:
            continue
        data = await uf.read()
        if not data.startswith(b"%PDF"):
            raise HTTPException(
                status_code=400,
                detail=f"Le fichier '{uf.filename}' n'est pas un PDF valide.",
            )
        saved_path = orch.store.save_uploaded_bytes(session.session_id, uf.filename, data)
        session.uploaded_files[saved_path.name] = str(saved_path)

    if len(session.uploaded_files) < 2:
        raise HTTPException(status_code=400, detail="Au moins 2 PDF distincts sont requis.")

    orch.store.save_session(session)

    if run_async:
        background_tasks.add_task(orch.run_verification, session.session_id)
        return session

    return orch.run_verification(session.session_id)


@router.post("/sessions/verify-local", response_model=VerificationSession)
def verify_local_files(req: LocalVerifyRequest) -> VerificationSession:
    """Create and run verification from local PDF paths on disk."""
    if len(req.file_paths) < 2:
        raise HTTPException(status_code=400, detail="Au moins 2 chemins PDF sont requis.")
    orch = _get_orchestrator()
    try:
        session = orch.create_session_from_paths(req.file_paths)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return orch.run_verification(
        session.session_id,
        explicit_v0=req.v0_filename,
        explicit_v1=req.v1_filename,
        explicit_n_minus_1=req.urd_n_minus_1_filename,
    )


@router.get("/sessions", response_model=list[VerificationSession])
def list_sessions() -> list[VerificationSession]:
    orch = _get_orchestrator()
    return orch.store.list_sessions()


@router.get("/sessions/{session_id}", response_model=VerificationSession)
def get_session(session_id: str) -> VerificationSession:
    orch = _get_orchestrator()
    try:
        return orch.store.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/versions/confirm", response_model=VerificationSession)
def confirm_or_swap_versions(
    session_id: str, req: VersionOverrideRequest
) -> VerificationSession:
    """HITL version confirmation: swap or confirm V0/V1/N-1 and re-run verification."""
    orch = _get_orchestrator()
    try:
        return orch.override_versions_and_rerun(session_id, req)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/findings", response_model=list[Finding])
def list_findings(
    session_id: str,
    diff_category: DiffCategory | None = None,
    control_type: ControlType | None = None,
    automation_level: AutomationLevel | None = None,
    severity: Severity | None = None,
    hitl_status: HITLStatus | None = None,
    requires_human_action: bool | None = None,
    page: int | None = None,
) -> list[Finding]:
    """Filterable findings list for UI sidebar & PDF page overlay."""
    orch = _get_orchestrator()
    try:
        session = orch.store.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    results = session.findings
    if diff_category is not None:
        results = [f for f in results if f.diff_category == diff_category]
    if control_type is not None:
        results = [f for f in results if f.control_type == control_type]
    if automation_level is not None:
        results = [f for f in results if f.automation_level == automation_level]
    if severity is not None:
        results = [f for f in results if f.severity == severity]
    if hitl_status is not None:
        results = [f for f in results if f.hitl_status == hitl_status]
    if requires_human_action is not None:
        results = [f for f in results if f.requires_human_action == requires_human_action]
    if page is not None:
        results = [
            f
            for f in results
            if (f.v1_location and f.v1_location.page_number == page)
            or (f.v0_location and f.v0_location.page_number == page)
        ]
    return results


@router.post(
    "/sessions/{session_id}/findings/{finding_id}/review",
    response_model=Finding,
)
def review_finding(
    session_id: str, finding_id: str, decision: HITLDecisionRequest
) -> Finding:
    """Record a Human-in-the-Loop decision on a specific finding."""
    orch = _get_orchestrator()
    hitl = HITLManager()
    try:
        session = orch.store.load_session(session_id)
        updated = hitl.apply_decision(session, finding_id, decision)
        orch.store.save_session(session)
        return updated
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/findings/batch-review")
def batch_review_findings(
    session_id: str, req: BatchReviewRequest
) -> dict[str, int | str]:
    orch = _get_orchestrator()
    hitl = HITLManager()
    try:
        session = orch.store.load_session(session_id)
        count = hitl.apply_batch_decision(session, req.finding_ids, req.decision)
        orch.store.save_session(session)
        return {"updated": count, "status": session.status}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/pdfs/{role}")
def get_original_pdf(
    session_id: str, role: Literal["v0", "v1", "urd_n_minus_1"]
) -> FileResponse:
    """Serve the original V0, V1, or URD N-1 PDF for the UI viewer."""
    orch = _get_orchestrator()
    try:
        session = orch.store.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not session.version_detection:
        raise HTTPException(status_code=400, detail="Versions non encore détectées.")
    filename = {
        "v0": session.version_detection.v0_filename,
        "v1": session.version_detection.v1_filename,
        "urd_n_minus_1": session.version_detection.urd_n_minus_1_filename,
    }.get(role)
    if not filename or filename not in session.uploaded_files:
        raise HTTPException(status_code=404, detail=f"Document '{role}' indisponible.")
    try:
        local_path = orch.store.ensure_local_file(
            session_id, "pdfs", session.uploaded_files[filename]
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path=str(local_path),
        media_type="application/pdf",
        filename=filename,
    )


@router.get("/sessions/{session_id}/export/annotated/{role}")
def download_annotated_pdf(
    session_id: str, role: Literal["v0", "v1"]
) -> FileResponse:
    """Download the V0 or V1 PDF with embedded color-coded highlights and notes."""
    orch = _get_orchestrator()
    try:
        session = orch.store.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    target = session.annotated_v0_path if role == "v0" else session.annotated_v1_path
    if not target:
        raise HTTPException(status_code=404, detail="PDF annoté indisponible.")
    try:
        local_path = orch.store.ensure_local_file(session_id, "exports", target)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="PDF annoté indisponible.") from exc
    return FileResponse(
        path=str(local_path),
        media_type="application/pdf",
        filename=local_path.name,
    )


@router.get("/sessions/{session_id}/export/report")
def download_markdown_report(session_id: str) -> PlainTextResponse:
    orch = _get_orchestrator()
    try:
        session = orch.store.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PlainTextResponse(content=session.executive_summary, media_type="text/markdown")


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict[str, str]:
    orch = _get_orchestrator()
    orch.store.delete_session(session_id)
    return {"deleted": session_id}


# =============================================================================
# Tickmark UI Integration Endpoints (docs/API_CONTRACT.md)
# =============================================================================


class TickmarkReviewItem(BaseModel):
    id: str
    status: Literal["pending", "confirmed", "dismissed"]
    note: str = ""
    reviewedBy: str | None = None
    reviewedAt: str | None = None


class TickmarkReviewPayload(BaseModel):
    differences: list[TickmarkReviewItem]


@router.post("/comparisons")
async def create_tickmark_comparison(
    clientId: str = Form(...),
    before: UploadFile = File(...),
    after: UploadFile = File(...),
    beforeSha256: str = Form(default=""),
    afterSha256: str = Form(default=""),
) -> dict[str, Any]:
    """Run full urd-verifier-agent comparison and return exact Tickmark UI payload."""
    before_bytes = await before.read()
    after_bytes = await after.read()

    if not before_bytes.startswith(b"%PDF-") or not after_bytes.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=400,
            detail="Un des fichiers fournis n'est pas un PDF valide (signature %PDF- manquante).",
        )

    calc_before_sha = hashlib.sha256(before_bytes).hexdigest()
    calc_after_sha = hashlib.sha256(after_bytes).hexdigest()

    if beforeSha256 and calc_before_sha.lower() != beforeSha256.strip().lower():
        raise HTTPException(
            status_code=409,
            detail=f"Intégrité compromise : empreinte SHA-256 de '{before.filename}' non conforme.",
        )
    if afterSha256 and calc_after_sha.lower() != afterSha256.strip().lower():
        raise HTTPException(
            status_code=409,
            detail=f"Intégrité compromise : empreinte SHA-256 de '{after.filename}' non conforme.",
        )

    orch = _get_orchestrator()
    session = orch.create_session_empty()

    before_name = f"before__{Path(before.filename or 'before.pdf').name}"
    after_name = f"after__{Path(after.filename or 'after.pdf').name}"
    p_before = orch.store.save_uploaded_bytes(session.session_id, before_name, before_bytes)
    p_after = orch.store.save_uploaded_bytes(session.session_id, after_name, after_bytes)
    session.uploaded_files[before_name] = str(p_before)
    session.uploaded_files[after_name] = str(p_after)
    orch.store.save_session(session)

    session = orch.run_verification(
        session.session_id,
        explicit_v0=before_name,
        explicit_v1=after_name,
    )

    payload, diff_to_finding = build_tickmark_response(
        session=session,
        before_pdf_path=p_before,
        after_pdf_path=p_after,
        llm_provider=orch.llm.provider,
    )
    orch.store.save_json_artifact(
        session.session_id,
        "tickmark_meta.json",
        {
            "clientId": clientId,
            "beforeSha256": calc_before_sha,
            "afterSha256": calc_after_sha,
            "diff_to_finding": diff_to_finding,
        },
    )
    return payload


@router.put("/comparisons/{comparison_id}/review", status_code=204)
def save_tickmark_review(
    comparison_id: str, payload: TickmarkReviewPayload
) -> Response:
    """Persist Tickmark HITL decisions back into the agent VerificationSession & audit trail."""
    orch = _get_orchestrator()
    try:
        session = orch.store.load_session(comparison_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    meta = orch.store.load_json_artifact(comparison_id, "tickmark_meta.json") or {}
    diff_to_finding: dict[str, str] = meta.get("diff_to_finding", {})

    status_map = {
        "pending": HITLStatus.PENDING_REVIEW,
        "confirmed": HITLStatus.CONFIRMED_ERROR,
        "dismissed": HITLStatus.ACCEPTED_CHANGE,
    }
    hitl = HITLManager()
    for item in payload.differences:
        fid = diff_to_finding.get(item.id)
        if not fid:
            continue
        try:
            hitl.apply_decision(
                session,
                fid,
                HITLDecisionRequest(
                    auditor_name=item.reviewedBy or "Auditeur Tickmark",
                    new_status=status_map[item.status],
                    comment=item.note or "",
                ),
            )
        except KeyError:
            continue

    orch.store.save_json_artifact(
        comparison_id,
        "tickmark_review.json",
        payload.model_dump(),
    )
    orch.store.save_session(session)
    return Response(status_code=204)


@router.post("/comparisons/{comparison_id}/send")
def send_tickmark_report(
    comparison_id: str, report: dict[str, Any]
) -> dict[str, Any]:
    """Record finalized client-portal report (confirmed errors only) in session store & GCS."""
    orch = _get_orchestrator()
    try:
        orch.store.load_session(comparison_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    orch.store.save_json_artifact(comparison_id, "tickmark_client_report.json", report)
    return report
