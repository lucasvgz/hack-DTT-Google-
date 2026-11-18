"""Summary metrics calculation and executive Markdown report generation."""

from __future__ import annotations

from collections import Counter

from urd_verifier.models.findings import Finding, HITLStatus, Severity
from urd_verifier.models.session import SessionSummary, VersionDetectionResult


class ReportGenerator:
    """Computes aggregated session metrics and human-readable Markdown summaries."""

    def compute_summary(self, findings: list[Finding]) -> SessionSummary:
        by_diff = Counter(f.diff_category.value for f in findings)
        by_ctrl = Counter(f.control_type.value for f in findings)
        by_auto = Counter(f.automation_level.value for f in findings)
        by_sev = Counter(f.severity.value for f in findings)
        by_hitl = Counter(f.hitl_status.value for f in findings)

        pending_human = sum(
            1
            for f in findings
            if f.requires_human_action and f.hitl_status == HITLStatus.PENDING_REVIEW
        )
        confirmed_errors = sum(
            1 for f in findings if f.hitl_status == HITLStatus.CONFIRMED_ERROR
        )
        accepted_changes = sum(
            1 for f in findings if f.hitl_status == HITLStatus.ACCEPTED_CHANGE
        )

        unresolved_critical = any(
            f.severity == Severity.CRITICAL
            and f.hitl_status not in {HITLStatus.ACCEPTED_CHANGE, HITLStatus.FALSE_POSITIVE}
            for f in findings
        )
        if unresolved_critical:
            readiness = "blocked_critical_errors"
        elif pending_human > 0 or confirmed_errors > 0:
            readiness = "review_required"
        else:
            readiness = "ready"

        return SessionSummary(
            total_findings=len(findings),
            by_diff_category=dict(by_diff),
            by_control_type=dict(by_ctrl),
            by_automation_level=dict(by_auto),
            by_severity=dict(by_sev),
            by_hitl_status=dict(by_hitl),
            pending_human_checks=pending_human,
            confirmed_errors=confirmed_errors,
            accepted_changes=accepted_changes,
            overall_readiness=readiness,  # type: ignore[arg-type]
        )

    def build_markdown_summary(
        self,
        version_detection: VersionDetectionResult,
        findings: list[Finding],
        summary: SessionSummary,
    ) -> str:
        lines: list[str] = [
            "# Rapport de Vérification URD — V0 vs V1",
            "",
            "## 1. Identification des Versions",
            f"- **V0 (référence initiale)** : `{version_detection.v0_filename}`",
            f"- **V1 (version à valider)** : `{version_detection.v1_filename}`",
        ]
        if version_detection.urd_n_minus_1_filename:
            lines.append(
                f"- **URD N-1 (comparatif publié)** : `{version_detection.urd_n_minus_1_filename}`"
            )
        lines.extend(
            [
                f"- **Confiance** : {version_detection.confidence:.0%} ({version_detection.rationale})",
                "",
                "## 2. Synthèse Globale",
                f"- **Total anomalies & différences** : {summary.total_findings}",
                f"- **Critiques** : {summary.by_severity.get('critical', 0)} | **Majeures** : {summary.by_severity.get('major', 0)} | **Mineures** : {summary.by_severity.get('minor', 0)} | **Info** : {summary.by_severity.get('info', 0)}",
                f"- **Points en attente de revue humaine (HITL)** : {summary.pending_human_checks}",
                f"- **Statut de préparation dépôt AMF** : `{summary.overall_readiness}`",
                "",
                "## 3. Répartition des Différences (Forme / Contenu / Chiffrage / ...)",
            ]
        )
        for cat, cnt in sorted(summary.by_diff_category.items()):
            lines.append(f"- **{cat}** : {cnt}")

        lines.extend(["", "## 4. Répartition par Type de Contrôle"])
        for ctrl, cnt in sorted(summary.by_control_type.items()):
            lines.append(f"- **{ctrl}** : {cnt}")

        criticals = [f for f in findings if f.severity == Severity.CRITICAL]
        if criticals:
            lines.extend(["", "## 5. Anomalies Critiques Prioritaires"])
            for f in criticals[:15]:
                loc = f.v1_location or f.v0_location
                pg = f"p.{loc.page_number}" if loc else "n/a"
                lines.append(
                    f"- **[{f.control_type.value}]** ({pg}) {f.title} — {f.description}"
                )

        return "\n".join(lines)
