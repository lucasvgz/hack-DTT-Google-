"""Disk + Google Cloud Storage (GCS) persistent store for Cloud Run & local execution."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from urd_verifier.models.session import VerificationSession


class SessionStore:
    """Manages session persistence locally and optionally mirrors to Google Cloud Storage."""

    def __init__(
        self,
        data_dir: str | Path,
        gcs_bucket: str | None = None,
        gcs_prefix: str = "urd-sessions",
        gcs_client: Any | None = None,
    ) -> None:
        self.base_dir = Path(data_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.gcs_bucket_name = gcs_bucket or None
        self.gcs_prefix = gcs_prefix.strip("/")
        self._gcs_client = gcs_client
        self._bucket: Any | None = None

    @property
    def is_gcs_enabled(self) -> bool:
        return bool(self.gcs_bucket_name)

    def _get_bucket(self) -> Any | None:
        if not self.gcs_bucket_name:
            return None
        if self._bucket is None:
            if self._gcs_client is None:
                from google.cloud import storage

                self._gcs_client = storage.Client()
            self._bucket = self._gcs_client.bucket(self.gcs_bucket_name)
        return self._bucket

    def _blob_name(self, session_id: str, *parts: str) -> str:
        rel = "/".join(p.strip("/") for p in parts if p)
        if self.gcs_prefix:
            return f"{self.gcs_prefix}/{session_id}/{rel}"
        return f"{session_id}/{rel}"

    def _upload_file(self, local_path: Path, session_id: str, *blob_parts: str) -> None:
        bucket = self._get_bucket()
        if bucket is None or not local_path.exists():
            return
        blob = bucket.blob(self._blob_name(session_id, *blob_parts))
        blob.upload_from_filename(str(local_path))

    def _download_file(self, local_path: Path, session_id: str, *blob_parts: str) -> bool:
        bucket = self._get_bucket()
        if bucket is None:
            return False
        blob = bucket.blob(self._blob_name(session_id, *blob_parts))
        if not blob.exists():
            return False
        local_path.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(local_path))
        return True

    def session_dir(self, session_id: str) -> Path:
        p = self.base_dir / session_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def files_dir(self, session_id: str) -> Path:
        p = self.session_dir(session_id) / "pdfs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def renders_dir(self, session_id: str) -> Path:
        p = self.session_dir(session_id) / "renders"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def exports_dir(self, session_id: str) -> Path:
        p = self.session_dir(session_id) / "exports"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def save_session(self, session: VerificationSession) -> None:
        session.updated_at = datetime.now(timezone.utc).isoformat()
        target = self.session_dir(session.session_id) / "session.json"
        target.write_text(session.model_dump_json(indent=2), encoding="utf-8")
        self._upload_file(target, session.session_id, "session.json")

    def load_session(self, session_id: str) -> VerificationSession:
        target = self.base_dir / session_id / "session.json"
        if not target.exists():
            downloaded = self._download_file(target, session_id, "session.json")
            if not downloaded:
                raise FileNotFoundError(f"Session '{session_id}' not found.")
        return VerificationSession.model_validate_json(target.read_text(encoding="utf-8"))

    def list_sessions(self) -> list[VerificationSession]:
        session_ids: set[str] = set()
        for entry in self.base_dir.iterdir():
            if entry.is_dir() and (entry / "session.json").is_file():
                session_ids.add(entry.name)

        bucket = self._get_bucket()
        if bucket is not None:
            prefix = f"{self.gcs_prefix}/" if self.gcs_prefix else ""
            for blob in bucket.list_blobs(prefix=prefix):
                name = blob.name[len(prefix) :] if prefix else blob.name
                parts = name.split("/")
                if len(parts) == 2 and parts[1] == "session.json":
                    session_ids.add(parts[0])

        sessions: list[VerificationSession] = []
        for sid in session_ids:
            try:
                sessions.append(self.load_session(sid))
            except Exception:
                continue
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def save_uploaded_bytes(self, session_id: str, filename: str, data: bytes) -> Path:
        safe_name = Path(filename).name
        dst = self.files_dir(session_id) / safe_name
        dst.write_bytes(data)
        self._upload_file(dst, session_id, "pdfs", safe_name)
        return dst

    def copy_local_pdf(self, session_id: str, src_path: str | Path) -> Path:
        src = Path(src_path)
        if not src.exists():
            raise FileNotFoundError(f"PDF not found: {src}")
        dst = self.files_dir(session_id) / src.name
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        self._upload_file(dst, session_id, "pdfs", dst.name)
        return dst

    def save_export_file(self, session_id: str, local_path: str | Path) -> Path:
        p = Path(local_path)
        self._upload_file(p, session_id, "exports", p.name)
        return p

    def save_json_artifact(self, session_id: str, filename: str, data: Any) -> Path:
        import json

        target = self.session_dir(session_id) / filename
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self._upload_file(target, session_id, filename)
        return target

    def load_json_artifact(self, session_id: str, filename: str) -> Any | None:
        import json

        target = self.session_dir(session_id) / filename
        if not target.exists():
            if not self._download_file(target, session_id, filename):
                return None
        return json.loads(target.read_text(encoding="utf-8"))

    def ensure_local_file(
        self, session_id: str, subfolder: str, path_or_name: str | Path
    ) -> Path:
        """Return a local file path, pulling from GCS if running on another Cloud Run instance."""
        p = Path(path_or_name)
        if p.exists():
            return p
        local_target = self.session_dir(session_id) / subfolder / p.name
        if local_target.exists():
            return local_target
        if self._download_file(local_target, session_id, subfolder, p.name):
            return local_target
        raise FileNotFoundError(f"File '{p.name}' not found locally or in GCS.")

    def delete_session(self, session_id: str) -> None:
        target = self.base_dir / session_id
        if target.exists():
            shutil.rmtree(target)
        bucket = self._get_bucket()
        if bucket is not None:
            prefix = self._blob_name(session_id, "")
            for blob in bucket.list_blobs(prefix=prefix):
                blob.delete()
