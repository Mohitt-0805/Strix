"""Adapter selecting real or fake pipeline based on USE_FAKE_PIPELINE."""

import os
from typing import Callable


def get_run() -> Callable[..., object]:
    """Return fake_pipeline.run if USE_FAKE_PIPELINE is truthy, else run_pipeline.run."""
    flag = os.environ.get("USE_FAKE_PIPELINE", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        from pipeline.fake_pipeline import run

        return run

    from pipeline.run_pipeline import run

    return run
