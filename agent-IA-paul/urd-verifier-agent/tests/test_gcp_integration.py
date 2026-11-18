"""Tests for GCP Cloud Run configuration, Vertex AI resolution, and GCS stateless sync."""

from __future__ import annotations

from pathlib import Path

from scripts.generate_sample_urds import generate_samples
from urd_verifier.agent import HITLManager, VerificationOrchestrator
from urd_verifier.config import VerifierSettings, get_settings
from urd_verifier.models.findings import HITLStatus
from urd_verifier.models.session import HITLDecisionRequest
from urd_verifier.storage import SessionStore


class _FakeBlob:
    def __init__(self, name: str, store: dict[str, bytes]) -> None:
        self.name = name
        self._store = store

    def exists(self) -> bool:
        return self.name in self._store

    def upload_from_filename(self, filename: str) -> None:
        self._store[self.name] = Path(filename).read_bytes()

    def download_to_filename(self, filename: str) -> None:
        Path(filename).write_bytes(self._store[self.name])

    def delete(self) -> None:
        self._store.pop(self.name, None)


class _FakeBucket:
    def __init__(self, store: dict[str, bytes]) -> None:
        self._store = store

    def blob(self, name: str) -> _FakeBlob:
        return _FakeBlob(name, self._store)

    def list_blobs(self, prefix: str = "") -> list[_FakeBlob]:
        return [
            _FakeBlob(k, self._store)
            for k in sorted(self._store.keys())
            if k.startswith(prefix)
        ]


class _FakeGCSClient:
    def __init__(self) -> None:
        self.buckets: dict[str, dict[str, bytes]] = {}

    def bucket(self, name: str) -> _FakeBucket:
        return _FakeBucket(self.buckets.setdefault(name, {}))


def test_cloud_run_and_vertexai_settings(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "urd-verifier-agent")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-gcp-project")
    monkeypatch.setenv("URD_VERTEX_LOCATION", "europe-west1")
    monkeypatch.setenv("URD_GCS_BUCKET", "my-urd-bucket")
    monkeypatch.delenv("URD_DATA_DIR", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("URD_LLM_PROVIDER", "auto")

    settings = get_settings()
    assert settings.is_cloud_run is True
    assert settings.data_dir == Path("/tmp/urd_sessions")
    assert settings.resolve_active_provider() == "vertexai"
    assert settings.vertex_project == "my-gcp-project"
    assert settings.vertex_location == "europe-west1"
    assert settings.gcs_bucket == "my-urd-bucket"


def test_gcs_stateless_container_sync_and_restore(tmp_path: Path):
    fake_gcs = _FakeGCSClient()
    pdf_dir = tmp_path / "sample_pdfs"
    paths = generate_samples(pdf_dir)

    # Container A (uploads & runs verification)
    dir_a = tmp_path / "container_a"
    store_a = SessionStore(
        dir_a, gcs_bucket="prod-urd-bucket", gcs_prefix="urd-sessions", gcs_client=fake_gcs
    )
    orch_a = VerificationOrchestrator(
        settings=VerifierSettings(llm_provider="offline", data_dir=dir_a),
        store=store_a,
    )
    session_a = orch_a.create_session_from_paths([paths["v0"], paths["v1"]])
    session_a = orch_a.run_verification(session_a.session_id)

    # Verify objects were mirrored into GCS
    bucket_objs = fake_gcs.buckets["prod-urd-bucket"]
    assert f"urd-sessions/{session_a.session_id}/session.json" in bucket_objs
    assert f"urd-sessions/{session_a.session_id}/pdfs/URD_2025_V0_Brouillon.pdf" in bucket_objs
    assert f"urd-sessions/{session_a.session_id}/pdfs/URD_2025_V1_Amende.pdf" in bucket_objs
    assert f"urd-sessions/{session_a.session_id}/exports/ANNOTATED_V1_URD_2025_V1_Amende.pdf" in bucket_objs

    # Container B (brand-new empty local disk!)
    dir_b = tmp_path / "container_b"
    store_b = SessionStore(
        dir_b, gcs_bucket="prod-urd-bucket", gcs_prefix="urd-sessions", gcs_client=fake_gcs
    )
    listed = store_b.list_sessions()
    assert any(s.session_id == session_a.session_id for s in listed)

    loaded_b = store_b.load_session(session_a.session_id)
    assert loaded_b.session_id == session_a.session_id

    # Restore original PDF & annotated PDF on Container B from GCS
    restored_v1 = store_b.ensure_local_file(
        session_a.session_id, "pdfs", "URD_2025_V1_Amende.pdf"
    )
    restored_ann = store_b.ensure_local_file(
        session_a.session_id, "exports", "ANNOTATED_V1_URD_2025_V1_Amende.pdf"
    )
    assert restored_v1.exists() and restored_v1.read_bytes().startswith(b"%PDF")
    assert restored_ann.exists() and restored_ann.read_bytes().startswith(b"%PDF")

    # Apply HITL review on Container B and verify it syncs back to GCS
    hitl = HITLManager()
    fid = loaded_b.findings[0].finding_id
    hitl.apply_decision(
        loaded_b,
        fid,
        HITLDecisionRequest(auditor_name="GCP_Auditor", new_status=HITLStatus.CONFIRMED_ERROR),
    )
    store_b.save_session(loaded_b)

    # Container C sees the updated HITL status from GCS
    dir_c = tmp_path / "container_c"
    store_c = SessionStore(
        dir_c, gcs_bucket="prod-urd-bucket", gcs_prefix="urd-sessions", gcs_client=fake_gcs
    )
    loaded_c = store_c.load_session(session_a.session_id)
    assert loaded_c.findings[0].hitl_status == HITLStatus.CONFIRMED_ERROR

    # Delete session clears GCS too
    store_c.delete_session(session_a.session_id)
    assert not any(k.startswith(f"urd-sessions/{session_a.session_id}/") for k in bucket_objs)
