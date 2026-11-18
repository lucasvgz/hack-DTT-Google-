"""Main Agentic Orchestrator coordinating ingestion, version detection, diffing, checks, and HITL."""

from __future__ import annotations

import uuid
from pathlib import Path

from urd_verifier.checks import AISemanticChecks, DeterministicChecks, HumanMandatoryChecks
from urd_verifier.config import VerifierSettings, get_settings
from urd_verifier.diff_engine import (
    DiffClassifier,
    DocumentAligner,
    TableDiffEngine,
    TextDiffEngine,
)
from urd_verifier.export import PDFAnnotator, ReportGenerator
from urd_verifier.ingestion import PDFParser, VersionDetector
from urd_verifier.models.document import ParsedPDF
from urd_verifier.models.findings import AuditAction, DiffCategory, Finding, Severity
from urd_verifier.models.session import (
    VerificationSession,
    VersionOverrideRequest,
)
from urd_verifier.storage import SessionStore
from .llm_client import LLMClient

_SEVERITY_RANK = {
    Severity.CRITICAL: 0,
    Severity.MAJOR: 1,
    Severity.MINOR: 2,
    Severity.INFO: 3,
}


class VerificationOrchestrator:
    """Orchestrates the end-to-end V0 vs V1 URD verification workflow."""

    def __init__(
        self,
        settings: VerifierSettings | None = None,
        store: SessionStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.store = store or SessionStore(
            self.settings.data_dir,
            gcs_bucket=self.settings.gcs_bucket,
            gcs_prefix=self.settings.gcs_prefix,
        )
        self.llm = LLMClient(self.settings)
        self.parser = PDFParser()
        self.version_detector = VersionDetector()
        self.aligner = DocumentAligner()
        self.text_diff = TextDiffEngine()
        self.table_diff = TableDiffEngine()
        self.classifier = DiffClassifier(self.settings)
        self.deterministic_checks = DeterministicChecks(self.settings)
        self.ai_checks = AISemanticChecks(self.settings, self.llm)
        self.human_checks = HumanMandatoryChecks(self.settings, self.llm)
        self.annotator = PDFAnnotator()
        self.reporter = ReportGenerator()

    def create_session_from_paths(self, pdf_paths: list[str | Path]) -> VerificationSession:
        if len(pdf_paths) < 2:
            raise ValueError("Au moins 2 fichiers PDF (V0 et V1) sont requis.")
        session_id = uuid.uuid4().hex[:12]
        uploaded_files: dict[str, str] = {}
        for p in pdf_paths:
            copied = self.store.copy_local_pdf(session_id, p)
            uploaded_files[copied.name] = str(copied)

        session = VerificationSession(
            session_id=session_id,
            status="created",
            uploaded_files=uploaded_files,
        )
        self.store.save_session(session)
        return session

    def create_session_empty(self) -> VerificationSession:
        session_id = uuid.uuid4().hex[:12]
        session = VerificationSession(session_id=session_id, status="created")
        self.store.save_session(session)
        return session

    def run_verification(
        self,
        session_id: str,
        explicit_v0: str | None = None,
        explicit_v1: str | None = None,
        explicit_n_minus_1: str | None = None,
    ) -> VerificationSession:
        session = self.store.load_session(session_id)
        try:
            session.status = "parsing"
            session.progress_pct = 10
            session.current_step = "Extraction structurelle et spatiale des PDF..."
            session.agent_trace = [
                f"[Agent] Démarrage vérification (provider LLM: {self.llm.provider}) sur {len(session.uploaded_files)} PDF."
            ]
            self.store.save_session(session)

            # 1. Parse PDFs (ensure local copy if running across stateless Cloud Run containers)
            render_dir = self.store.renders_dir(session_id)
            parsed_docs: dict[str, ParsedPDF] = {}
            for fname, fpath in session.uploaded_files.items():
                local_pdf = self.store.ensure_local_file(session_id, "pdfs", fpath)
                parsed = self.parser.parse(local_pdf, render_dir=render_dir)
                parsed_docs[fname] = parsed
                session.doc_info[fname] = {
                    "page_count": parsed.page_count,
                    "table_count": len(parsed.tables),
                    "section_count": len(parsed.sections),
                    "chart_count": len(parsed.charts),
                    "sections": [
                        {
                            "section_id": s.section_id,
                            "title": s.title,
                            "page_start": s.page_start,
                            "page_end": s.page_end,
                        }
                        for s in parsed.sections
                    ],
                }
                session.agent_trace.append(
                    f"[Ingestion] '{fname}' : {parsed.page_count} pages, {len(parsed.tables)} tableaux, "
                    f"{len(parsed.sections)} sections, {len(parsed.charts)} graphiques."
                )

            # 2. Detect V0 vs V1 (or apply explicit override)
            session.progress_pct = 25
            session.current_step = "Identification automatique des versions V0 et V1..."
            if explicit_v0 and explicit_v1:
                if explicit_v0 not in parsed_docs or explicit_v1 not in parsed_docs:
                    raise ValueError("Les noms de fichiers V0/V1 spécifiés sont introuvables.")
                det = self.version_detector.detect(list(parsed_docs.values()))
                det.v0_filename = explicit_v0
                det.v1_filename = explicit_v1
                det.urd_n_minus_1_filename = explicit_n_minus_1
                det.confirmed_by_human = True
                det.needs_human_confirmation = False
                det.rationale = f"Assignation confirmée par l'utilisateur : V0='{explicit_v0}', V1='{explicit_v1}'."
                session.version_detection = det
            else:
                session.version_detection = self.version_detector.detect(
                    list(parsed_docs.values())
                )

            session.status = "version_detected"
            session.agent_trace.append(
                f"[VersionDetector] {session.version_detection.rationale} "
                f"(confiance {session.version_detection.confidence:.0%})."
            )
            self.store.save_session(session)

            v0_doc = parsed_docs[session.version_detection.v0_filename]
            v1_doc = parsed_docs[session.version_detection.v1_filename]
            n1_doc = (
                parsed_docs.get(session.version_detection.urd_n_minus_1_filename)
                if session.version_detection.urd_n_minus_1_filename
                else None
            )

            # 3. Align & Diff V0 vs V1
            session.status = "verifying"
            session.progress_pct = 45
            session.current_step = "Alignement structurel et diff complet V0 vs V1 (forme, contenu, chiffrage)..."
            self.store.save_session(session)

            aligned_blocks = self.aligner.align_blocks(v0_doc, v1_doc)
            aligned_tables = self.aligner.align_tables(v0_doc, v1_doc)
            header_diffs = self.aligner.align_headers_footers(v0_doc, v1_doc)

            diff_findings: list[Finding] = []
            diff_findings.extend(self.text_diff.diff(v0_doc, v1_doc, aligned_blocks))
            diff_findings.extend(self.table_diff.diff(v0_doc, v1_doc, aligned_tables))
            diff_findings.extend(
                self.classifier.classify_header_diffs(v0_doc, v1_doc, header_diffs)
            )
            diff_findings = self.classifier.refine(diff_findings)
            session.agent_trace.append(
                f"[DiffEngine] {len(diff_findings)} différence(s) détectée(s) et classifiée(s) entre V0 et V1."
            )

            # 4. Deterministic checks (1-6)
            session.progress_pct = 65
            session.current_step = "Exécution des contrôles déterministes (arithmétique, variations, renvois, ESEF)..."
            self.store.save_session(session)
            det_findings = self.deterministic_checks.run(v0_doc, v1_doc, n1_doc)
            session.agent_trace.append(
                f"[DeterministicChecks] {len(det_findings)} anomalie(s) détectée(s) sur contrôles 100% automatisables."
            )

            # 5. AI + Vision semantic checks (7-11)
            session.progress_pct = 80
            session.current_step = "Contrôles sémantiques IA & Vision (inter-sections, texte/tableau, graphiques, CSRD)..."
            self.store.save_session(session)
            ai_findings = self.ai_checks.run(v0_doc, v1_doc, n1_doc)
            session.agent_trace.append(
                f"[AISemanticChecks] {len(ai_findings)} point(s) de cohérence détecté(s)."
            )

            # 6. Mandatory Human Checkpoints (12-15)
            session.progress_pct = 90
            session.current_step = "Génération des points de contrôle humain obligatoire (HITL)..."
            self.store.save_session(session)
            hitl_findings = self.human_checks.run(v0_doc, v1_doc, n1_doc)

            all_findings = diff_findings + det_findings + ai_findings + hitl_findings

            # Check 13: Materiality checkpoint for minor numeric diffs
            minor_numeric = [
                f
                for f in all_findings
                if f.diff_category == DiffCategory.CHIFFRAGE
                and f.severity in {Severity.MINOR, Severity.INFO}
                and f.is_material is False
            ]
            all_findings.extend(
                self.human_checks.build_materiality_checkpoint(v1_doc, minor_numeric)
            )

            # Add initial agent audit entry and sort by severity then page number
            for f in all_findings:
                if not f.audit_trail:
                    f.audit_trail.append(
                        AuditAction(
                            actor="agent",
                            action="detected",
                            new_status=f.hitl_status,
                            comment=f.ai_rationale or f.description[:140],
                        )
                    )

            all_findings.sort(
                key=lambda f: (
                    _SEVERITY_RANK.get(f.severity, 9),
                    (f.v1_location.page_number if f.v1_location else (f.v0_location.page_number if f.v0_location else 9999)),
                )
            )
            session.findings = all_findings

            # 7. Annotate V0 and V1 PDFs with exact highlights
            session.progress_pct = 95
            session.current_step = "Génération des PDF annotés et du rapport exécutif..."
            exports_dir = self.store.exports_dir(session_id)
            ann_v0 = self.annotator.annotate(
                v0_doc.file_path,
                exports_dir / f"ANNOTATED_V0_{v0_doc.filename}",
                all_findings,
                role="v0",
            )
            ann_v1 = self.annotator.annotate(
                v1_doc.file_path,
                exports_dir / f"ANNOTATED_V1_{v1_doc.filename}",
                all_findings,
                role="v1",
            )
            self.store.save_export_file(session_id, ann_v0)
            self.store.save_export_file(session_id, ann_v1)
            session.annotated_v0_path = str(ann_v0)
            session.annotated_v1_path = str(ann_v1)

            # 8. Compute summary & report
            session.summary = self.reporter.compute_summary(all_findings)
            session.executive_summary = self.reporter.build_markdown_summary(
                session.version_detection, all_findings, session.summary
            )
            session.progress_pct = 100
            session.current_step = "Vérification terminée — en attente de revue humaine (HITL)."
            session.status = (
                "completed"
                if session.summary.pending_human_checks == 0
                and session.summary.overall_readiness == "ready"
                else "awaiting_human_review"
            )
            session.agent_trace.append(
                f"[Orchestrator] Terminé : {session.summary.total_findings} findings "
                f"({session.summary.pending_human_checks} HITL en attente)."
            )
            self.store.save_session(session)
            return session

        except Exception as exc:
            session.status = "failed"
            session.error_message = str(exc)
            session.current_step = "Erreur lors de la vérification."
            session.agent_trace.append(f"[Error] {exc}")
            self.store.save_session(session)
            raise

    def override_versions_and_rerun(
        self, session_id: str, req: VersionOverrideRequest
    ) -> VerificationSession:
        return self.run_verification(
            session_id=session_id,
            explicit_v0=req.v0_filename,
            explicit_v1=req.v1_filename,
            explicit_n_minus_1=req.urd_n_minus_1_filename,
        )
