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
from backend.app.routes.audit import router as audit_router
from backend.app.routes.auth import router as auth_router
from backend.app.routes.clips import router as clips_router
from backend.app.routes.evidence import router as evidence_router
from backend.app.routes.files import router as files_router
from backend.app.routes.frames import router as frames_router
from backend.app.routes.indexes import router as indexes_router
from backend.app.routes.runs import router as runs_router
from backend.app.routes.search import router as search_router
from backend.app.routes.users import router as users_router
from backend.app.routes.zones import router as zones_router
from backend.app.security import LoginThrottle
from backend.app.services.jobs import JobManager, mark_stale_runs_failed
from backend.app.services.search_index import SearchIndex

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
    search_index = SearchIndex(embed_dim=cfg.embed_dim)
    job_manager = JobManager(
        session_factory=session_factory,
        settings=cfg,
        search_index=search_index,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        init_db(engine)
        stale_count = mark_stale_runs_failed(session_factory)
        if stale_count:
            logger.warning("Marked %d stale queued/running run(s) as SERVER_RESTARTED.", stale_count)
        with session_factory() as db:
            indexed_count = search_index.rebuild_from_db(db, cfg.resolved_data_dir)
        application.state.media_tools = check_media_tools()
        logger.info(
            "Strix backend started (pipeline_mode=%s, search_backend=%s, indexed_frames=%d).",
            cfg.pipeline_mode,
            search_index.backend_name,
            indexed_count,
        )
        yield
        job_manager.shutdown(wait=True)
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
    application.state.login_throttle = LoginThrottle()
    application.state.search_index = search_index
    application.state.job_manager = job_manager

    application.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(application)
    application.include_router(auth_router)
    application.include_router(users_router)
    application.include_router(audit_router)
    application.include_router(clips_router)
    application.include_router(files_router)
    application.include_router(runs_router)
    application.include_router(frames_router)
    application.include_router(indexes_router)
    application.include_router(search_router)
    application.include_router(evidence_router)
    application.include_router(zones_router)

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
            "demo_pack_enabled": cfg.demo_pack_enabled,
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
