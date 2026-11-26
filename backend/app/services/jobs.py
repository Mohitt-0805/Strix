"""Single-worker background job executor for pipeline runs."""

import logging
from concurrent.futures import Future, ThreadPoolExecutor

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.audit import record_audit
from backend.app.config import Settings
from backend.app.models import Clip, FrameRecord, Run, User, utc_now_naive
from backend.app.services.pipeline_gateway import execute_pipeline_for_run
from backend.app.services.search_index import (
    IndexItem,
    SearchIndex,
    load_and_normalize_embedding,
)
from backend.app.services.storage import from_rel

logger = logging.getLogger(__name__)


def mark_stale_runs_failed(session_factory: sessionmaker[Session]) -> int:
    """Mark any leftover queued/running runs as failed with SERVER_RESTARTED."""
    with session_factory() as db:
        stale = (
            db.execute(select(Run).where(Run.status.in_(["queued", "running"])))
            .scalars()
            .all()
        )
        if not stale:
            return 0
        now = utc_now_naive()
        for run in stale:
            run.status = "failed"
            run.stage = "failed"
            run.error_code = "SERVER_RESTARTED"
            run.error_message = "Processing was interrupted by a server restart."
            run.finished_at = now
        db.commit()
        return len(stale)


class JobManager:
    """Serializes pipeline runs on a single background worker thread."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        search_index: SearchIndex | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.search_index = search_index
        # Single worker protects the 4 GB demo GPU from concurrent ML runs.
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="strix-pipeline",
        )

    def _index_completed_run(self, db: Session, run: Run, clip: Clip) -> None:
        """Load finished run embeddings into the in-memory SearchIndex."""
        if self.search_index is None:
            return
        data_root = self.settings.resolved_data_dir
        frame_rows = (
            db.execute(
                select(FrameRecord)
                .where(FrameRecord.run_id == run.id)
                .order_by(FrameRecord.id.asc())
            )
            .scalars()
            .all()
        )
        items: list[IndexItem] = []
        for row in frame_rows:
            try:
                emb_path = from_rel(
                    row.embedding_path_rel,
                    data_root,
                    allowed_roots=("outputs",),
                )
            except Exception as exc:
                logger.warning(
                    "Skipping invalid embedding path for run %s frame %s: %s",
                    run.id,
                    row.frame_id,
                    exc,
                )
                continue
            vec = load_and_normalize_embedding(emb_path, self.settings.embed_dim)
            if vec is None:
                continue
            items.append(
                IndexItem(
                    clip_id=clip.id,
                    filename=clip.original_filename,
                    run_id=run.id,
                    frame_id=str(row.frame_id),
                    timestamp_sec=row.timestamp_sec,
                    reliability=row.reliability,
                    flags=tuple(row.flags or []),
                    frame_path_rel=row.frame_path_rel,
                    crop_path_rel=row.crop_path_rel,
                    vector=vec,
                )
            )
        self.search_index.remove_run(run.id)
        if items:
            self.search_index.add(items)

    def submit_run(self, run_id: int) -> Future[None]:
        """Queue a run_id onto the single-worker ThreadPoolExecutor."""
        return self._executor.submit(self._execute_run, run_id)

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the worker executor cleanly."""
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _execute_run(self, run_id: int) -> None:
        """Worker entrypoint using an isolated SQLAlchemy Session per job."""
        with self.session_factory() as db:
            run = db.get(Run, run_id)
            if run is None:
                logger.warning("Run %s disappeared before execution.", run_id)
                return
            clip = db.get(Clip, run.clip_id)
            if clip is None:
                run.status = "failed"
                run.stage = "failed"
                run.error_code = "CLIP_NOT_FOUND"
                run.error_message = "Source clip no longer exists."
                run.finished_at = utc_now_naive()
                db.commit()
                return

            user = db.get(User, run.created_by)
            username = user.username if user is not None else None
            role = user.role if user is not None else None

            run.status = "running"
            run.stage = "processing"
            run.progress = None
            run.started_at = utc_now_naive()
            db.commit()

            record_audit(
                db,
                action="process_started",
                user_id=run.created_by,
                username=username,
                role=role,
                target_type="run",
                target_id=str(run.id),
                details={"clip_id": run.clip_id, "pipeline_mode": run.pipeline_mode},
            )

            def _progress_cb(stage: str, progress: float | None = None) -> None:
                run_row = db.get(Run, run_id)
                if run_row is not None:
                    run_row.stage = stage
                    run_row.progress = progress
                    db.commit()

            try:
                result = execute_pipeline_for_run(
                    db=db,
                    run=run,
                    clip=clip,
                    settings=self.settings,
                    progress_cb=_progress_cb,
                )
                run.status = "done"
                run.stage = "done"
                run.progress = 1.0
                run.finished_at = utc_now_naive()
                db.commit()
                self._index_completed_run(db, run, clip)

                record_audit(
                    db,
                    action="process_finished",
                    user_id=run.created_by,
                    username=username,
                    role=role,
                    target_type="run",
                    target_id=str(run.id),
                    details={
                        "clip_id": run.clip_id,
                        "frame_count": len(result.best_frames),
                    },
                )
            except Exception as exc:
                logger.exception("Pipeline run %s failed", run_id)
                db.rollback()
                failed_run = db.get(Run, run_id)
                if failed_run is not None:
                    raw_code = getattr(exc, "code", None)
                    error_code = (
                        str(raw_code)
                        if isinstance(raw_code, str) and raw_code.strip()
                        else "PIPELINE_FAILED"
                    )
                    failed_run.status = "failed"
                    failed_run.stage = "failed"
                    failed_run.error_code = error_code
                    failed_run.error_message = (
                        str(exc).strip() or "Pipeline execution failed."
                    )
                    failed_run.finished_at = utc_now_naive()
                    db.commit()

                    record_audit(
                        db,
                        action="process_failed",
                        user_id=failed_run.created_by,
                        username=username,
                        role=role,
                        target_type="run",
                        target_id=str(failed_run.id),
                        details={"clip_id": failed_run.clip_id, "error_code": error_code},
                    )
