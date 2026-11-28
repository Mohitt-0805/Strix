"""Single-worker PriorityQueue job manager for runs (prio 0) and indexes (prio 1)."""

import itertools
import logging
import queue
import threading
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from backend.app.audit import record_audit
from backend.app.config import Settings
from backend.app.models import (
    Clip,
    ClipIndex,
    FrameRecord,
    IndexFaceRecord,
    Run,
    User,
    utc_now_naive,
)
from backend.app.services.pipeline_gateway import (
    execute_index_for_job,
    execute_pipeline_for_run,
)
from backend.app.services.search_index import (
    IndexItem,
    SearchIndex,
    load_and_normalize_embedding,
)
from backend.app.services.storage import from_rel
from backend.app.services.warmup import WarmupManager

logger = logging.getLogger(__name__)

PRIORITY_RUN = 0
PRIORITY_INDEX = 1

_ERROR_ADVICE_MAP: dict[str, str] = {
    "VIDEO_NOT_FOUND": "The uploaded file is missing, re-upload it",
    "VideoNotFound": "The uploaded file is missing, re-upload it",
    "VIDEO_UNREADABLE": (
        "Export the clip as MP4 (H.264) from the DVR/NVR software "
        "or convert it with FFmpeg"
    ),
    "VideoUnreadable": (
        "Export the clip as MP4 (H.264) from the DVR/NVR software "
        "or convert it with FFmpeg"
    ),
    "ZONE_NOT_FOUND": "No ATM zone is stored for this clip, pick a known zone or draw one",
    "ZoneNotFound": "No ATM zone is stored for this clip, pick a known zone or draw one",
    "MODEL_LOAD": (
        "The pipeline models failed to load, check the weights and GPU "
        "on the pipeline machine"
    ),
    "MODEL_LOAD_ERROR": (
        "The pipeline models failed to load, check the weights and GPU "
        "on the pipeline machine"
    ),
    "ModelLoad": (
        "The pipeline models failed to load, check the weights and GPU "
        "on the pipeline machine"
    ),
}


def get_error_advice(error_code: str, error_message: str) -> str | None:
    """Map typed pipeline error codes to investigator-facing remediation advice."""
    if error_code in {"INVALID_ARGUMENT", "InvalidArgument"}:
        return error_message
    return _ERROR_ADVICE_MAP.get(error_code)


def mark_stale_runs_failed(session_factory: sessionmaker[Session]) -> int:
    """Mark leftover queued/running runs and index jobs as failed with SERVER_RESTARTED."""
    with session_factory() as db:
        now = utc_now_naive()
        count = 0
        for model in (Run, ClipIndex):
            stale = (
                db.execute(select(model).where(model.status.in_(["queued", "running"])))
                .scalars()
                .all()
            )
            for row in stale:
                row.status = "failed"
                row.stage = "failed"
                row.error_code = "SERVER_RESTARTED"
                row.error_message = "Processing was interrupted by a server restart."
                row.finished_at = now
                count += 1
        if count:
            db.commit()
        return count


class JobManager:
    """Serializes run (priority 0) and index (priority 1) jobs on ONE worker thread."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        search_index: SearchIndex | None = None,
        warmup_manager: WarmupManager | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.search_index = search_index
        self.warmup_manager = warmup_manager
        self._queue: queue.PriorityQueue[tuple[int, int, str, int]] = queue.PriorityQueue()
        self._counter = itertools.count()
        self._stopping = False
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="strix-job-worker",
            daemon=True,
        )
        self._worker.start()

    def submit_run(self, run_id: int) -> None:
        """Queue a processing run with high priority (0)."""
        self._queue.put((PRIORITY_RUN, next(self._counter), "run", run_id))

    def submit_index(self, index_id: int) -> None:
        """Queue a clip indexing job with background priority (1)."""
        self._queue.put((PRIORITY_INDEX, next(self._counter), "index", index_id))

    def shutdown(self, wait: bool = True) -> None:
        """Signal worker to exit after any currently running job finishes."""
        self._stopping = True
        self._queue.put((PRIORITY_RUN, next(self._counter), "shutdown", 0))
        if wait and self._worker.is_alive():
            self._worker.join(timeout=30.0)

    def _wait_for_warmup(self) -> dict[str, Any] | None:
        """Wait until startup warmup finishes (or shutdown is requested) and return snapshot."""
        if self.warmup_manager is None:
            return None
        while not self._stopping:
            if self.warmup_manager.wait(timeout=0.05):
                return self.warmup_manager.snapshot()
        return None

    def _fail_job_for_warmup(self, kind: str, job_id: int, warmup_snap: dict[str, Any]) -> None:
        """Mark a queued/new Run or ClipIndex failed with MODEL_LOAD using warmup warnings."""
        warnings = [str(w).strip() for w in (warmup_snap.get("warnings") or []) if str(w).strip()]
        msg_raw = str(warmup_snap.get("message") or "").strip()
        if warnings:
            joined_warnings = "; ".join(warnings)
            error_msg = (
                joined_warnings
                if (not msg_raw or msg_raw in joined_warnings)
                else f"{msg_raw}; {joined_warnings}"
            )
        else:
            error_msg = msg_raw or "Model warmup failed."

        advice = get_error_advice("MODEL_LOAD", error_msg)
        with self.session_factory() as db:
            model = Run if kind == "run" else ClipIndex
            row = db.get(model, job_id)
            if row is None:
                return
            row.status = "failed"
            row.stage = "failed"
            row.error_code = "MODEL_LOAD"
            row.error_message = error_msg
            row.error_advice = advice
            row.finished_at = utc_now_naive()
            db.commit()

            user = db.get(User, row.created_by)
            record_audit(
                db,
                action="process_failed" if kind == "run" else "index_failed",
                user_id=row.created_by,
                username=user.username if user is not None else None,
                role=user.role if user is not None else None,
                target_type="run" if kind == "run" else "clip_index",
                target_id=str(row.id),
                details={"clip_id": row.clip_id, "error_code": "MODEL_LOAD"},
            )

    def _worker_loop(self) -> None:
        """Pop highest-priority job one at a time without starting before warmup finishes."""
        while not self._stopping:
            _prio, _seq, kind, job_id = self._queue.get()
            try:
                if kind == "shutdown" or self._stopping:
                    break
                warmup_snap = self._wait_for_warmup()
                if self._stopping:
                    break
                if warmup_snap is not None and warmup_snap.get("state") == "failed":
                    self._fail_job_for_warmup(kind, job_id, warmup_snap)
                    continue
                if kind == "run":
                    self._execute_run(job_id)
                elif kind == "index":
                    self._execute_index(job_id)
            except Exception:
                logger.exception("Unexpected error in worker loop for %s=%s", kind, job_id)
            finally:
                self._queue.task_done()

    def _make_progress_cb(self, db: Session, model: type[Run] | type[ClipIndex], row_id: int):
        """Build an exception-safe progress callback for Run or ClipIndex."""

        def _progress_cb(
            event_or_stage: Any,
            fraction_arg: float | None = None,
        ) -> None:
            try:
                if isinstance(event_or_stage, dict):
                    stage_val = event_or_stage.get("stage")
                    raw_frac = event_or_stage.get("fraction")
                    msg_val = event_or_stage.get("message")
                else:
                    stage_val = event_or_stage
                    raw_frac = fraction_arg
                    msg_val = None

                values: dict[str, Any] = {}
                if stage_val is not None:
                    values["stage"] = str(stage_val)
                if raw_frac is not None:
                    values["progress"] = float(raw_frac)
                if msg_val is not None:
                    values["progress_message"] = str(msg_val)
                if not values:
                    return

                db.execute(update(model).where(model.id == row_id).values(**values))
                db.commit()
            except Exception as cb_exc:
                logger.warning(
                    "Ignoring error in progress_cb for %s %s: %s",
                    model.__tablename__,
                    row_id,
                    cb_exc,
                )
                try:
                    db.rollback()
                except Exception:
                    pass

        return _progress_cb

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
            if not row.embedding_path_rel:
                continue
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
                    source="run",
                    clip_id=clip.id,
                    filename=clip.original_filename,
                    run_id=run.id,
                    frame_id=str(row.frame_id),
                    timestamp_sec=row.timestamp_sec,
                    reliability=row.reliability,
                    flags=tuple(row.flags or []),
                    flag_scores=dict(row.flag_scores) if row.flag_scores else None,
                    frame_path_rel=row.frame_path_rel,
                    crop_path_rel=row.crop_path_rel,
                    vector=vec,
                    track_id=None,
                    short_track=False,
                )
            )
        self.search_index.remove_run(run.id)
        if items:
            self.search_index.add(items)

    def _index_completed_clip_index(
        self, db: Session, index_job: ClipIndex, clip: Clip
    ) -> None:
        """Load finished ClipIndex face embeddings into the in-memory SearchIndex."""
        if self.search_index is None:
            return
        data_root = self.settings.resolved_data_dir
        face_rows = (
            db.execute(
                select(IndexFaceRecord)
                .where(IndexFaceRecord.index_id == index_job.id)
                .order_by(IndexFaceRecord.id.asc())
            )
            .scalars()
            .all()
        )
        items: list[IndexItem] = []
        for row in face_rows:
            if not row.embedding_rel:
                continue
            try:
                emb_path = from_rel(
                    row.embedding_rel,
                    data_root,
                    allowed_roots=("outputs",),
                )
            except Exception as exc:
                logger.warning(
                    "Skipping invalid embedding path for index %s track %s t=%s: %s",
                    index_job.id,
                    row.track_id,
                    row.t,
                    exc,
                )
                continue
            vec = load_and_normalize_embedding(emb_path, self.settings.embed_dim)
            if vec is None:
                continue
            items.append(
                IndexItem(
                    source="index",
                    clip_id=clip.id,
                    filename=clip.original_filename,
                    run_id=None,
                    index_id=index_job.id,
                    frame_id=None,
                    t=row.t,
                    timestamp_sec=row.t,
                    track_id=row.track_id,
                    short_track=bool(row.short_track),
                    reliability=row.reliability,
                    flags=tuple(row.flags or []),
                    flag_scores=dict(row.flag_scores) if row.flag_scores else None,
                    frame_path_rel=row.frame_rel,
                    crop_path_rel=row.crop_rel,
                    vector=vec,
                )
            )
        self.search_index.remove_index(index_job.id)
        if items:
            self.search_index.add(items)

    def _execute_run(self, run_id: int) -> None:
        """Execute a single Run using an isolated SQLAlchemy Session."""
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

            progress_cb = self._make_progress_cb(db, Run, run_id)

            try:
                result = execute_pipeline_for_run(
                    db=db,
                    run=run,
                    clip=clip,
                    settings=self.settings,
                    progress_cb=progress_cb,
                )
                run_row = db.get(Run, run_id)
                if run_row is not None:
                    if run_row.stage != "done" or not run_row.progress_message:
                        run_row.progress_message = "Done"
                    run_row.status = "done"
                    run_row.stage = "done"
                    run_row.progress = 1.0
                    run_row.finished_at = utc_now_naive()
                    db.commit()
                    self._index_completed_run(db, run_row, clip)

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
                    error_msg = str(exc).strip() or "Pipeline execution failed."
                    failed_run.status = "failed"
                    failed_run.stage = "failed"
                    failed_run.error_code = error_code
                    failed_run.error_message = error_msg
                    failed_run.error_advice = get_error_advice(error_code, error_msg)
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

    def _execute_index(self, index_id: int) -> None:
        """Execute a single ClipIndex job using an isolated SQLAlchemy Session."""
        with self.session_factory() as db:
            index_job = db.get(ClipIndex, index_id)
            if index_job is None:
                logger.warning("ClipIndex %s disappeared before execution.", index_id)
                return
            clip = db.get(Clip, index_job.clip_id)
            if clip is None:
                index_job.status = "failed"
                index_job.stage = "failed"
                index_job.error_code = "CLIP_NOT_FOUND"
                index_job.error_message = "Source clip no longer exists."
                index_job.finished_at = utc_now_naive()
                db.commit()
                return

            user = db.get(User, index_job.created_by)
            username = user.username if user is not None else None
            role = user.role if user is not None else None

            index_job.status = "running"
            index_job.stage = "indexing"
            index_job.progress = None
            index_job.started_at = utc_now_naive()
            db.commit()

            record_audit(
                db,
                action="index_started",
                user_id=index_job.created_by,
                username=username,
                role=role,
                target_type="clip_index",
                target_id=str(index_job.id),
                details={"clip_id": index_job.clip_id, "pipeline_mode": index_job.pipeline_mode},
            )

            progress_cb = self._make_progress_cb(db, ClipIndex, index_id)

            try:
                result = execute_index_for_job(
                    db=db,
                    index_job=index_job,
                    clip=clip,
                    settings=self.settings,
                    progress_cb=progress_cb,
                )
                idx_row = db.get(ClipIndex, index_id)
                if idx_row is not None:
                    if idx_row.stage != "done" or not idx_row.progress_message:
                        idx_row.progress_message = "Done"
                    idx_row.status = "done"
                    idx_row.stage = "done"
                    idx_row.progress = 1.0
                    idx_row.finished_at = utc_now_naive()
                    db.commit()
                    self._index_completed_clip_index(db, idx_row, clip)

                record_audit(
                    db,
                    action="index_finished",
                    user_id=index_job.created_by,
                    username=username,
                    role=role,
                    target_type="clip_index",
                    target_id=str(index_job.id),
                    details={
                        "clip_id": index_job.clip_id,
                        "total_embeddings": int(result.total_embeddings),
                    },
                )
            except Exception as exc:
                logger.exception("Index job %s failed", index_id)
                db.rollback()
                failed_idx = db.get(ClipIndex, index_id)
                if failed_idx is not None:
                    raw_code = getattr(exc, "code", None)
                    error_code = (
                        str(raw_code)
                        if isinstance(raw_code, str) and raw_code.strip()
                        else "PIPELINE_FAILED"
                    )
                    error_msg = str(exc).strip() or "Clip indexing failed."
                    failed_idx.status = "failed"
                    failed_idx.stage = "failed"
                    failed_idx.error_code = error_code
                    failed_idx.error_message = error_msg
                    failed_idx.error_advice = get_error_advice(error_code, error_msg)
                    failed_idx.finished_at = utc_now_naive()
                    db.commit()

                    record_audit(
                        db,
                        action="index_failed",
                        user_id=failed_idx.created_by,
                        username=username,
                        role=role,
                        target_type="clip_index",
                        target_id=str(failed_idx.id),
                        details={"clip_id": failed_idx.clip_id, "error_code": error_code},
                    )
