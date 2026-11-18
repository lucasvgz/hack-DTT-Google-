"""FastAPI application factory with CORS (credentials-safe), error formatting, and optional UI hosting."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from urd_verifier.config import get_settings
from .routes import router


def _resolve_ui_dir() -> Path | None:
    explicit = os.getenv("URD_STATIC_UI_DIR", "").strip()
    if explicit:
        p = Path(explicit)
        return p if (p / "index.html").is_file() else None
    # Auto-detect repo root if running from agent-IA-paul/urd-verifier-agent
    parents = Path(__file__).resolve().parents
    if len(parents) > 5:
        candidate = parents[5]
        if (candidate / "index.html").is_file() and (candidate / "js" / "api.js").is_file():
            return candidate
    return None


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Tickmark · URD Verifier Agent API",
        description=(
            "API agentique de vérification V0 vs V1 des Documents d'Enregistrement Universel (URD) "
            "connectée à l'UI Tickmark avec localisation exacte, 15 contrôles URD et Human-in-the-Loop."
        ),
        version="0.2.0",
    )

    # Support credentials: "include" from localhost / GitHub Pages / Cloud Run
    wildcard = settings.cors_origins == ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[] if wildcard else settings.cors_origins,
        allow_origin_regex=".*" if wildcard else None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "error": {"message": msg}},
        )

    app.include_router(router)

    ui_dir = _resolve_ui_dir()
    if ui_dir is not None:
        app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="tickmark-ui")

    return app


app = create_app()
