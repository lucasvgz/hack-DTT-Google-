"""Configuration management for the URD Verifier Agent (Local + GCP Cloud Run)."""

from __future__ import annotations

import os
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


def _default_data_dir() -> Path:
    explicit = os.getenv("URD_DATA_DIR", "").strip()
    if explicit:
        return Path(explicit)
    # Cloud Run writable local cache directory
    if os.getenv("K_SERVICE") or os.getenv("URD_GCS_BUCKET"):
        return Path("/tmp/urd_sessions")
    return Path(__file__).resolve().parents[2] / "data" / "sessions"


class VerifierSettings(BaseModel):
    """Runtime settings for verification tolerances, LLM provider, and GCP storage."""

    llm_provider: str = Field(
        default_factory=lambda: os.getenv("URD_LLM_PROVIDER", "auto")
    )
    llm_model: str = Field(
        default_factory=lambda: os.getenv("URD_LLM_MODEL", "")
    )
    openai_api_key: str | None = Field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY") or None
    )
    gemini_api_key: str | None = Field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY") or None
    )
    anthropic_api_key: str | None = Field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY") or None
    )

    # GCP Vertex AI & Cloud Storage settings
    vertex_project: str | None = Field(
        default_factory=lambda: (
            os.getenv("URD_VERTEX_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or None
        )
    )
    vertex_location: str = Field(
        default_factory=lambda: os.getenv("URD_VERTEX_LOCATION", "europe-west1")
    )
    gcs_bucket: str | None = Field(
        default_factory=lambda: os.getenv("URD_GCS_BUCKET") or None
    )
    gcs_prefix: str = Field(
        default_factory=lambda: os.getenv("URD_GCS_PREFIX", "urd-sessions")
    )

    # Verification tolerances
    arithmetic_tolerance: float = Field(
        default_factory=lambda: float(os.getenv("URD_ARITHMETIC_TOLERANCE", "1.0"))
    )
    variation_tolerance_pct: float = Field(
        default_factory=lambda: float(os.getenv("URD_VARIATION_TOLERANCE_PCT", "0.15"))
    )
    materiality_threshold_eur: float = Field(
        default_factory=lambda: float(os.getenv("URD_MATERIALITY_THRESHOLD_EUR", "500000.0"))
    )
    materiality_threshold_pct: float = Field(
        default_factory=lambda: float(os.getenv("URD_MATERIALITY_THRESHOLD_PCT", "0.5"))
    )

    # Storage & API
    data_dir: Path = Field(default_factory=_default_data_dir)
    cors_origins: list[str] = Field(
        default_factory=lambda: os.getenv("URD_CORS_ORIGINS", "*").split(",")
    )

    @property
    def is_cloud_run(self) -> bool:
        return bool(os.getenv("K_SERVICE"))

    def resolve_active_provider(self) -> str:
        """Resolve which LLM backend is active based on settings, API keys, or GCP Vertex AI."""
        provider = self.llm_provider.lower().strip()
        if provider == "offline":
            return "offline"
        if provider == "vertexai":
            return "vertexai" if self.vertex_project else "offline"
        if provider in {"openai", "gemini", "anthropic"}:
            key_map = {
                "openai": self.openai_api_key,
                "gemini": self.gemini_api_key,
                "anthropic": self.anthropic_api_key,
            }
            return provider if key_map[provider] else "offline"
        # Auto mode: prefer Vertex AI when running on GCP with a project configured
        if self.vertex_project and (self.is_cloud_run or not (self.gemini_api_key or self.openai_api_key or self.anthropic_api_key)):
            return "vertexai"
        if self.gemini_api_key:
            return "gemini"
        if self.openai_api_key:
            return "openai"
        if self.anthropic_api_key:
            return "anthropic"
        return "offline"


def get_settings() -> VerifierSettings:
    """Return a fresh VerifierSettings instance."""
    return VerifierSettings()
