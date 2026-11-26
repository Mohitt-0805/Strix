"""FastAPI application factory and Phase 1 core endpoints."""

import logging
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import (
    ACCEPTED_VIDEO_EXTENSIONS,
    FAKE_BANNER_TEXT,
    HUMAN_VERIFICATION_NOTICE,
    Settings,
    get_settings,
)
from backend.app.db import check_db, create_db_engine, create_session_factory, init_db
from backend.app.errors import AppError, register_error_handlers

logger = logging.getLogger(__name__)


def check_media_tools() -> dict[str, bool]:
    """Check whether ffmpeg and ffprobe binaries exist on PATH."""
    status = {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
    }
    for tool, available in status.items():
        if not available:
            logger.warning(
                "%s binary not found on PATH; video probing and extraction will fail.",
                tool,
            )
    return status


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application instance."""
    cfg = settings or get_settings()
    engine = create_db_engine(cfg.db_path)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        init_db(engine)
        application.state.media_tools = check_media_tools()
        logger.info("Strix backend started (pipeline_mode=%s).", cfg.pipeline_mode)
        yield
        engine.dispose()

    application = FastAPI(
        title="Strix Backend API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = cfg
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.media_tools = check_media_tools()

    application.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(application)

    @application.get("/health")
    def health(request: Request) -> dict[str, object]:
        """Report service health, database connectivity, and media tool availability."""
        if not check_db(request.app.state.engine):
            raise AppError(
                status_code=503,
                code="DB_UNAVAILABLE",
                detail="Database health check failed.",
            )
        tools: dict[str, bool] = request.app.state.media_tools
        return {
            "status": "ok",
            "db": "ok",
            "pipeline_mode": cfg.pipeline_mode,
            "ffmpeg": tools.get("ffmpeg", False),
            "ffprobe": tools.get("ffprobe", False),
        }

    @application.get("/config/public")
    def public_config() -> dict[str, object]:
        """Return public non-secret configuration, limits, and verification notice."""
        is_fake = cfg.use_fake_pipeline
        return {
            "pipeline_mode": cfg.pipeline_mode,
            "banner": FAKE_BANNER_TEXT if is_fake else None,
            "notice": HUMAN_VERIFICATION_NOTICE,
            "limits": {
                "max_upload_mb": cfg.max_upload_mb,
                "window_sec_min": 1,
                "window_sec_max": 100,
                "sample_fps_min": 0.5,
                "sample_fps_max": 5.0,
                "max_sampled_frames": 200,
                "embed_dim": cfg.embed_dim,
                "signed_url_ttl_sec": cfg.signed_url_ttl_sec,
            },
            "accepted_extensions": list(ACCEPTED_VIDEO_EXTENSIONS),
            "model_labels": ["FAKE PIPELINE"] if is_fake else cfg.model_labels_list,
            "display_tz": cfg.display_tz,
        }

    return application


app = create_app()
