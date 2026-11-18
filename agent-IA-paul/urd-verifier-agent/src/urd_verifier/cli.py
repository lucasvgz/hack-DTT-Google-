"""Command-line interface for running URD V0 vs V1 verification and launching the API server."""

from __future__ import annotations

from pathlib import Path
import json
import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from urd_verifier.agent import VerificationOrchestrator

app = typer.Typer(help="URD Verifier Agent — Vérification V0 vs V1 et Human-in-the-Loop")
console = Console()


@app.command()
def verify(
    pdfs: list[Path] = typer.Argument(..., help="Chemins vers V0, V1 (et optionnellement URD N-1)"),
    output_json: Path | None = typer.Option(None, "--json", "-j", help="Sauvegarder la session JSON"),
) -> None:
    """Vérifie 2+ PDF URD, identifie V0/V1, classe les écarts et génère les PDF annotés."""
    orch = VerificationOrchestrator()
    session = orch.create_session_from_paths([str(p) for p in pdfs])
    session = orch.run_verification(session.session_id)

    vd = session.version_detection
    if vd:
        console.print(f"\n[bold cyan]Versions détectées[/bold cyan] (confiance {vd.confidence:.0%}) :")
        console.print(f"  • V0 : [yellow]{vd.v0_filename}[/yellow]")
        console.print(f"  • V1 : [green]{vd.v1_filename}[/green]")
        if vd.urd_n_minus_1_filename:
            console.print(f"  • URD N-1 : [blue]{vd.urd_n_minus_1_filename}[/blue]")

    tbl = Table(title=f"Résultats Session {session.session_id} ({session.summary.total_findings} findings)")
    tbl.add_column("Sévérité", style="bold")
    tbl.add_column("Catégorie Diff")
    tbl.add_column("Contrôle")
    tbl.add_column("Page")
    tbl.add_column("Titre")
    tbl.add_column("HITL")

    for f in session.findings:
        loc = f.v1_location or f.v0_location
        pg = str(loc.page_number) if loc else "-"
        tbl.add_row(
            f.severity.value,
            f.diff_category.value,
            f.control_type.value,
            pg,
            f.title[:65],
            "Oui" if f.requires_human_action else "Non",
        )
    console.print(tbl)
    console.print(f"\nPDF annoté V0 : {session.annotated_v0_path}")
    console.print(f"PDF annoté V1 : {session.annotated_v1_path}")

    if output_json:
        output_json.write_text(session.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"JSON exporté : {output_json}")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Host d'écoute"),
    port: int = typer.Option(8000, help="Port d'écoute"),
    reload: bool = typer.Option(False, help="Activer le rechargement à chaud"),
) -> None:
    """Démarre le serveur FastAPI pour l'intégration avec l'UI."""
    uvicorn.run("urd_verifier.api.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
