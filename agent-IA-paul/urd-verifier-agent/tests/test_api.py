"""Integration tests for the FastAPI REST API consumed by the colleague's UI."""

from pathlib import Path
from fastapi.testclient import TestClient

from scripts.generate_sample_urds import generate_samples
from urd_verifier.api.main import create_app


def test_api_upload_verify_filter_review_and_exports(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("URD_DATA_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("URD_LLM_PROVIDER", "offline")

    pdf_dir = tmp_path / "pdfs"
    paths = generate_samples(pdf_dir)

    app = create_app()
    client = TestClient(app)

    # 1. Health & taxonomy
    r_health = client.get("/api/v1/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "ok"

    r_tax = client.get("/api/v1/taxonomy")
    assert r_tax.status_code == 200
    assert len(r_tax.json()["control_types"]) == 16

    # 2. Multipart PDF upload (simulating colleague's UI)
    files = [
        ("files", ("URD_2025_V0_Brouillon.pdf", paths["v0"].read_bytes(), "application/pdf")),
        ("files", ("URD_2025_V1_Amende.pdf", paths["v1"].read_bytes(), "application/pdf")),
        ("files", ("URD_2024_Publie.pdf", paths["urd_n_minus_1"].read_bytes(), "application/pdf")),
    ]
    r_verify = client.post("/api/v1/sessions/verify", files=files)
    assert r_verify.status_code == 200
    session_data = r_verify.json()
    sid = session_data["session_id"]
    assert session_data["version_detection"]["v0_filename"] == "URD_2025_V0_Brouillon.pdf"
    assert session_data["version_detection"]["v1_filename"] == "URD_2025_V1_Amende.pdf"
    assert session_data["summary"]["total_findings"] > 10

    # 3. Filter findings by diff_category=chiffrage
    r_filt = client.get(f"/api/v1/sessions/{sid}/findings?diff_category=chiffrage")
    assert r_filt.status_code == 200
    chiffrage_findings = r_filt.json()
    assert len(chiffrage_findings) >= 1

    # 4. HITL review
    fid = chiffrage_findings[0]["finding_id"]
    r_rev = client.post(
        f"/api/v1/sessions/{sid}/findings/{fid}/review",
        json={
            "auditor_name": "Marie",
            "new_status": "accepted_change",
            "comment": "Validé avec le DAF.",
            "is_material": False,
        },
    )
    assert r_rev.status_code == 200
    assert r_rev.json()["hitl_status"] == "accepted_change"

    # 5. Serve original V1 PDF & annotated V1 PDF & Markdown report
    r_pdf = client.get(f"/api/v1/sessions/{sid}/pdfs/v1")
    assert r_pdf.status_code == 200
    assert r_pdf.content.startswith(b"%PDF")

    r_ann = client.get(f"/api/v1/sessions/{sid}/export/annotated/v1")
    assert r_ann.status_code == 200
    assert r_ann.content.startswith(b"%PDF")

    r_rep = client.get(f"/api/v1/sessions/{sid}/export/report")
    assert r_rep.status_code == 200
    assert "Rapport de Vérification URD" in r_rep.text
