"""Integration tests for the Tickmark UI contract endpoints (/api/v1/comparisons)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from urd_verifier.api.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLES_DIR = REPO_ROOT / "samples"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_tickmark_static_ui_and_cors(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("URD_DATA_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("URD_LLM_PROVIDER", "offline")
    monkeypatch.setenv("URD_STATIC_UI_DIR", str(REPO_ROOT))

    app = create_app()
    client = TestClient(app)

    r_root = client.get("/")
    assert r_root.status_code == 200
    assert "Tickmark" in r_root.text

    r_cfg = client.get("/js/config.js")
    assert r_cfg.status_code == 200
    assert "API_BASE_URL" in r_cfg.text

    r_preflight = client.options(
        "/api/v1/comparisons",
        headers={
            "Origin": "https://example.github.io",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r_preflight.status_code == 200
    assert r_preflight.headers.get("access-control-allow-origin") == "https://example.github.io"
    assert r_preflight.headers.get("access-control-allow-credentials") == "true"


def test_tickmark_comparisons_validation_errors(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("URD_DATA_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("URD_LLM_PROVIDER", "offline")

    v1_bytes = (SAMPLES_DIR / "URD_2025_v1_precedente.pdf").read_bytes()
    v2_bytes = (SAMPLES_DIR / "URD_2025_v2_nouvelle.pdf").read_bytes()

    app = create_app()
    client = TestClient(app)

    # Non-PDF rejected with 400 + error.message
    r_bad_mime = client.post(
        "/api/v1/comparisons",
        data={"clientId": "alpha"},
        files={
            "before": ("not_a_pdf.txt", b"hello", "text/plain"),
            "after": ("v2.pdf", v2_bytes, "application/pdf"),
        },
    )
    assert r_bad_mime.status_code == 400
    assert "message" in r_bad_mime.json().get("error", {})

    # Wrong SHA-256 rejected with 409 + error.message
    r_bad_sha = client.post(
        "/api/v1/comparisons",
        data={
            "clientId": "alpha",
            "beforeSha256": "0" * 64,
            "afterSha256": _sha256_hex(v2_bytes),
        },
        files={
            "before": ("URD_2025_v1_precedente.pdf", v1_bytes, "application/pdf"),
            "after": ("URD_2025_v2_nouvelle.pdf", v2_bytes, "application/pdf"),
        },
    )
    assert r_bad_sha.status_code == 409
    assert "SHA-256" in r_bad_sha.json().get("error", {}).get("message", "")


def test_tickmark_full_comparison_review_and_send(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("URD_DATA_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("URD_LLM_PROVIDER", "offline")

    v1_path = SAMPLES_DIR / "URD_2025_v1_precedente.pdf"
    v2_path = SAMPLES_DIR / "URD_2025_v2_nouvelle.pdf"
    v1_bytes = v1_path.read_bytes()
    v2_bytes = v2_path.read_bytes()

    app = create_app()
    client = TestClient(app)

    r_comp = client.post(
        "/api/v1/comparisons",
        data={
            "clientId": "alpha",
            "beforeSha256": _sha256_hex(v1_bytes),
            "afterSha256": _sha256_hex(v2_bytes),
        },
        headers={"Origin": "https://example.github.io"},
        files={
            "before": (v1_path.name, v1_bytes, "application/pdf"),
            "after": (v2_path.name, v2_bytes, "application/pdf"),
        },
    )
    assert r_comp.status_code == 200
    assert r_comp.headers.get("access-control-allow-origin") == "https://example.github.io"
    assert r_comp.headers.get("access-control-allow-credentials") == "true"

    data = r_comp.json()
    comp_id = data["id"]
    assert data["engine"].startswith("urd-verifier-agent+")

    before_doc = data["documents"]["before"]
    after_doc = data["documents"]["after"]
    before_text = before_doc["text"]
    after_text = after_doc["text"]
    assert before_doc["pageCount"] >= 1
    assert after_doc["pageCount"] >= 1
    assert "\f" in before_text
    assert "\f" in after_text

    diffs = data["differences"]
    assert len(diffs) >= 5

    # Every hunk must match exact slice offsets
    for d in diffs:
        bs, be = d["beforeRange"]
        as_, ae = d["afterRange"]
        assert 0 <= bs <= be <= len(before_text)
        assert 0 <= as_ <= ae <= len(after_text)
        assert d["before"] == before_text[bs:be]
        assert d["after"] == after_text[as_:ae]
        assert d.get("status", "pending") == "pending"

    # Non-overlapping intervals on both sides when sorted as renderDoc() does
    before_spans = sorted(
        [(d["beforeRange"][0], d["beforeRange"][1], d["id"]) for d in diffs if d["beforeRange"][1] > d["beforeRange"][0]],
        key=lambda x: (x[0], x[1]),
    )
    for (_, e1, id1), (s2, _, id2) in zip(before_spans, before_spans[1:]):
        assert e1 <= s2, f"Overlap on beforeRange between {id1} and {id2}: {e1} > {s2}"

    after_spans = sorted(
        [(d["afterRange"][0], d["afterRange"][1], d["id"]) for d in diffs if d["afterRange"][1] > d["afterRange"][0]],
        key=lambda x: (x[0], x[1]),
    )
    for (_, e1, id1), (s2, _, id2) in zip(after_spans, after_spans[1:]):
        assert e1 <= s2, f"Overlap on afterRange between {id1} and {id2}: {e1} > {s2}"

    categories = {d["category"] for d in diffs}
    assert "chiffres" in categories
    assert "versionDetection" in data
    assert "agentSummary" in data

    # Persist HITL decisions via PUT /api/v1/comparisons/{id}/review
    review_payload = {
        "differences": [
            {
                "id": diffs[0]["id"],
                "status": "confirmed",
                "note": "Écart validé pour restitution client.",
                "reviewedBy": "Lucas Giovinazzo",
                "reviewedAt": "2026-11-18T15:30:00Z",
            },
            {
                "id": diffs[-1]["id"],
                "status": "dismissed",
                "note": "Correction acceptable.",
                "reviewedBy": "Lucas Giovinazzo",
                "reviewedAt": "2026-11-18T15:31:00Z",
            },
        ]
    }
    r_rev = client.put(f"/api/v1/comparisons/{comp_id}/review", json=review_payload)
    assert r_rev.status_code == 204

    # Underlying VerificationSession must reflect linked finding HITL updates if any linked diff was reviewed
    r_sess = client.get(f"/api/v1/sessions/{comp_id}")
    assert r_sess.status_code == 200
    assert r_sess.json()["findings"]

    # Persist final client report via POST /api/v1/comparisons/{id}/send
    client_report = {
        "clientId": "alpha",
        "beforeFile": v1_path.name,
        "afterFile": v2_path.name,
        "confirmedCount": 1,
        "items": [review_payload["differences"][0]],
    }
    r_send = client.post(f"/api/v1/comparisons/{comp_id}/send", json=client_report)
    assert r_send.status_code == 200
    assert r_send.json()["confirmedCount"] == 1
