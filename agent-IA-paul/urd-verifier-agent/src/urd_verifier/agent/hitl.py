"""Human-in-the-Loop (HITL) decision engine and audit trail manager."""

from __future__ import annotations

from urd_verifier.export.report import ReportGenerator
from urd_verifier.models.findings import AuditAction, Finding, HITLStatus
from urd_verifier.models.session import HITLDecisionRequest, VerificationSession


class HITLManager:
    """Applies auditor decisions, records audit trail, and updates session readiness."""

    def __init__(self) -> None:
        self.reporter = ReportGenerator()

    def apply_decision(
        self,
        session: VerificationSession,
        finding_id: str,
        decision: HITLDecisionRequest,
    ) -> Finding:
        target = next((f for f in session.findings if f.finding_id == finding_id), None)
        if target is None:
            raise KeyError(f"Finding '{finding_id}' not found in session '{session.session_id}'.")

        prev_status = target.hitl_status
        target.hitl_status = decision.new_status
        if decision.comment:
            target.reviewer_comment = decision.comment
        if decision.is_material is not None:
            target.is_material = decision.is_material
        if decision.override_severity is not None:
            target.severity = decision.override_severity

        target.audit_trail.append(
            AuditAction(
                actor=f"auditor:{decision.auditor_name}",
                action="hitl_review",
                previous_status=prev_status,
                new_status=decision.new_status,
                comment=decision.comment,
            )
        )

        self._refresh_session_summary(session)
        return target

    def apply_batch_decision(
        self,
        session: VerificationSession,
        finding_ids: list[str],
        decision: HITLDecisionRequest,
    ) -> int:
        updated = 0
        id_set = set(finding_ids)
        for target in session.findings:
            if target.finding_id not in id_set:
                continue
            prev_status = target.hitl_status
            target.hitl_status = decision.new_status
            if decision.comment:
                target.reviewer_comment = decision.comment
            if decision.is_material is not None:
                target.is_material = decision.is_material
            if decision.override_severity is not None:
                target.severity = decision.override_severity
            target.audit_trail.append(
                AuditAction(
                    actor=f"auditor:{decision.auditor_name}",
                    action="hitl_batch_review",
                    previous_status=prev_status,
                    new_status=decision.new_status,
                    comment=decision.comment,
                )
            )
            updated += 1

        self._refresh_session_summary(session)
        return updated

    def _refresh_session_summary(self, session: VerificationSession) -> None:
        session.summary = self.reporter.compute_summary(session.findings)
        if session.version_detection:
            session.executive_summary = self.reporter.build_markdown_summary(
                session.version_detection, session.findings, session.summary
            )
        if (
            session.summary.pending_human_checks == 0
            and session.summary.overall_readiness == "ready"
        ):
            session.status = "completed"
        elif session.status == "completed":
            session.status = "awaiting_human_review"
