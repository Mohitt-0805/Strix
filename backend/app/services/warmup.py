"""Thread-safe startup model warmup manager (non-blocking background thread)."""

import inspect
import logging
import os
import threading
import time
from typing import Any

from backend.app.config import Settings
from pipeline.contract import WarmupResult

logger = logging.getLogger(__name__)


class WarmupManager:
    """Runs pipeline.adapter.get_warmup() once on a background thread and tracks state."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._done_event = threading.Event()
        self._started = False
        self._thread: threading.Thread | None = None

        if settings.warmup_on_start:
            self._state = "running"
            self._progress: float = 0.0
            self._message: str = "Models loading..."
            self._warnings: list[str] = []
            self._total_ms: float | None = None
            self._providers: dict[str, str | None] = {}
            self._loaded: dict[str, bool | None] = {}
        else:
            self._state = "ok"
            self._progress = 1.0
            self._message = "Warmup skipped (WARMUP_ON_START=0)"
            self._warnings = []
            self._total_ms = 0.0
            self._providers = {}
            self._loaded = {}
            self._done_event.set()

    def start(self) -> None:
        """Start the single background warmup thread once (non-blocking)."""
        if not self.settings.warmup_on_start:
            return
        with self._lock:
            if self._started:
                return
            self._started = True
            self._thread = threading.Thread(
                target=self._run,
                name="strix-warmup",
                daemon=True,
            )
            self._thread.start()

    @property
    def is_ready(self) -> bool:
        """Return True only when warmup finished cleanly with state=='ok'."""
        with self._lock:
            return self._state == "ok"

    @property
    def state(self) -> str:
        """Return current warmup state ('running' | 'ok' | 'failed')."""
        with self._lock:
            return self._state

    def snapshot(self) -> dict[str, Any]:
        """Return a thread-safe copy of the warmup state block."""
        with self._lock:
            return {
                "state": self._state,
                "progress": self._progress,
                "message": self._message,
                "warnings": list(self._warnings),
                "total_ms": self._total_ms,
                "providers": dict(self._providers),
                "loaded": dict(self._loaded),
            }

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for warmup completion up to timeout seconds."""
        return self._done_event.wait(timeout=timeout)

    def _on_progress(self, event: Any) -> None:
        """Update progress/message safely from pipeline warmup callback dict."""
        if not isinstance(event, dict):
            return
        raw_frac = event.get("fraction")
        raw_msg = event.get("message")
        with self._lock:
            if self._state != "running":
                return
            if raw_frac is not None:
                try:
                    frac = float(raw_frac)
                    self._progress = max(0.0, min(1.0, frac))
                except (TypeError, ValueError):
                    pass
            if raw_msg is not None:
                self._message = str(raw_msg)

    def _run(self) -> None:
        """Invoke pipeline.adapter.get_warmup() once and record WarmupResult or error."""
        t0 = time.perf_counter()
        try:
            os.environ["USE_FAKE_PIPELINE"] = (
                "1" if self.settings.use_fake_pipeline else "0"
            )
            from pipeline.adapter import get_warmup

            warmup_fn = get_warmup()
            sig = inspect.signature(warmup_fn)
            accepts_cb = "progress_cb" in sig.parameters or any(
                p.kind == inspect.Parameter.VAR_KEYWORD
                for p in sig.parameters.values()
            )
            raw = warmup_fn(progress_cb=self._on_progress) if accepts_cb else warmup_fn()
            res = (
                raw
                if isinstance(raw, WarmupResult)
                else WarmupResult.model_validate(raw)
            )
            warnings = [str(w) for w in (res.warnings or []) if str(w).strip()]
            providers = {str(k): (str(v) if v is not None else None) for k, v in (res.providers or {}).items()}
            loaded = {str(k): (bool(v) if v is not None else None) for k, v in (res.loaded or {}).items()}
            elapsed_ms = (
                float(res.total_ms)
                if res.total_ms is not None
                else round((time.perf_counter() - t0) * 1000.0, 2)
            )

            with self._lock:
                self._warnings = warnings
                self._providers = providers
                self._loaded = loaded
                self._total_ms = elapsed_ms
                if res.ok is True:
                    self._state = "ok"
                    self._progress = 1.0
                    if not self._message or self._message == "Models loading...":
                        self._message = "Warmup complete"
                else:
                    self._state = "failed"
                    self._message = (
                        "; ".join(warnings)
                        if warnings
                        else "Model warmup reported failure (ok is not True)."
                    )
        except Exception as exc:
            logger.exception("Model warmup failed with exception")
            err_msg = str(exc).strip() or type(exc).__name__
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            with self._lock:
                self._state = "failed"
                self._message = err_msg
                if err_msg not in self._warnings:
                    self._warnings = [*self._warnings, err_msg]
                self._total_ms = elapsed_ms
        finally:
            self._done_event.set()
