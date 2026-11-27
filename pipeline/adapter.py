"""Adapter selecting real or fake pipeline based on USE_FAKE_PIPELINE."""

import os
from typing import Callable


def _use_fake() -> bool:
    flag = os.environ.get("USE_FAKE_PIPELINE", "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def get_run() -> Callable[..., object]:
    """Return fake_pipeline.run if USE_FAKE_PIPELINE is truthy, else run_pipeline.run."""
    if _use_fake():
        from pipeline.fake_pipeline import run

        return run

    from pipeline.run_pipeline import run

    return run


def get_index_clip() -> Callable[..., object]:
    """Return fake_pipeline.index_clip if USE_FAKE_PIPELINE is truthy, else index_clip.index_clip."""
    if _use_fake():
        from pipeline.fake_pipeline import index_clip

        return index_clip

    from pipeline.index_clip import index_clip

    return index_clip


def get_search() -> Callable[..., object]:
    """Return fake_pipeline.search_with_enhancement if USE_FAKE_PIPELINE is truthy, else compare.search_with_enhancement."""
    if _use_fake():
        from pipeline.fake_pipeline import search_with_enhancement

        return search_with_enhancement

    from pipeline.compare import search_with_enhancement

    return search_with_enhancement
