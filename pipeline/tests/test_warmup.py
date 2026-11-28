"""Tests for Phase 8i: pipeline.warmup, fake_pipeline.warmup, and adapter.get_warmup."""

from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import numpy as np
import pytest

from pipeline.contract import WarmupResult
from pipeline.errors import ModelLoadError


def test_warmup_import_safety() -> None:
    """Importing pipeline.adapter, pipeline.warmup, and fake_pipeline must not load heavy libs."""
    code = (
        "import sys; "
        "import pipeline.adapter; "
        "import pipeline.warmup; "
        "import pipeline.fake_pipeline; "
        "loaded = [m for m in ('torch', 'cv2', 'insightface', 'onnxruntime', 'open_clip') if m in sys.modules]; "
        "assert not loaded, f'Unexpected heavy imports: {loaded}'"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr or res.stdout


def test_adapter_get_warmup_switches_fake_and_real(monkeypatch: pytest.MonkeyPatch) -> None:
    """adapter.get_warmup() returns fake_pipeline.warmup or warmup.warmup based on env."""
    from pipeline import adapter, fake_pipeline, warmup as warmup_mod

    monkeypatch.setenv("USE_FAKE_PIPELINE", "1")
    assert adapter.get_warmup() is fake_pipeline.warmup

    monkeypatch.setenv("USE_FAKE_PIPELINE", "0")
    assert adapter.get_warmup() is warmup_mod.warmup


def test_fake_warmup_instant_and_shape() -> None:
    """fake_pipeline.warmup() returns ok=True, all loaded=None, and 'fake pipeline' warning."""
    from pipeline import fake_pipeline

    events: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    res = fake_pipeline.warmup(progress_cb=events.append)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert isinstance(res, WarmupResult)
    assert res.ok is True
    assert res.loaded == {"person_detector": None, "face_model": None, "clip": None}
    assert any("fake pipeline" in w.lower() for w in res.warnings)
    assert elapsed_ms < 200.0
    assert events and all(e["stage"] == "warmup" for e in events)
    fracs = [float(e["fraction"]) for e in events]
    assert fracs == sorted(fracs) and fracs[-1] == 1.0


def test_warmup_idempotent_and_monotonic_with_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    """warmup() warms cached loaders once, is idempotent on repeat calls, and emits monotonic events."""
    from pipeline import detect_track as dt_mod
    from pipeline import faces as faces_mod
    from pipeline import occluders as occ_mod
    from pipeline import warmup as warmup_mod

    monkeypatch.setattr(warmup_mod, "_WARMED_INSTANCES", set())
    monkeypatch.setattr(warmup_mod, "_WARNED_MODELS", set())

    det_sentinel = object()
    face_calls = {"get": 0}
    clip_calls = {"score": 0}
    det_calls = {"detect": 0}

    class _StubFaceApp:
        def get(self, img: Any) -> list[Any]:
            face_calls["get"] += 1
            return []

    face_sentinel = _StubFaceApp()
    clip_sentinel = {"stub": True}

    monkeypatch.setattr(dt_mod, "load_person_detector", lambda *a, **kw: det_sentinel)
    monkeypatch.setattr(dt_mod, "get_device", lambda: "cpu")

    def _stub_detect_persons(frames: list[Any], **kw: Any) -> list[list[Any]]:
        det_calls["detect"] += 1
        return [[] for _ in frames]

    monkeypatch.setattr(dt_mod, "detect_persons", _stub_detect_persons)
    monkeypatch.setattr(faces_mod, "get_face_app", lambda: face_sentinel)
    monkeypatch.setattr(faces_mod, "get_active_provider", lambda: "CPUExecutionProvider")
    monkeypatch.setattr(occ_mod, "get_model", lambda *a, **kw: clip_sentinel)

    def _stub_clip_score(crops: list[Any], **kw: Any) -> tuple[list[list[Any]], list[dict[str, float]]]:
        clip_calls["score"] += 1
        return [[] for _ in crops], [{} for _ in crops]

    monkeypatch.setattr(occ_mod, "score_occluders_batch", _stub_clip_score)

    events1: list[dict[str, Any]] = []
    res1 = warmup_mod.warmup(progress_cb=events1.append)
    assert isinstance(res1, WarmupResult)
    assert res1.ok is True
    assert res1.loaded == {"person_detector": True, "face_model": True, "clip": True}
    assert res1.providers == {"faces": "CPUExecutionProvider", "torch_device": "cpu"}
    assert res1.warnings == []
    assert det_calls["detect"] == 1
    assert face_calls["get"] == 1
    assert clip_calls["score"] == 1

    fracs1 = [float(e["fraction"]) for e in events1]
    assert all(e["stage"] == "warmup" for e in events1)
    assert fracs1 == sorted(fracs1) and fracs1[-1] == 1.0

    # Second call reuses warmed instance IDs and does not rerun dummy forward passes.
    res2 = warmup_mod.warmup()
    assert res2.ok is True
    assert res2.loaded == {"person_detector": True, "face_model": True, "clip": True}
    assert det_calls["detect"] == 1
    assert face_calls["get"] == 1
    assert clip_calls["score"] == 1


def test_warmup_clip_failure_is_non_critical(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLIP failure returns ok=True with loaded['clip']=False and a warning even with include_critical=True."""
    from pipeline import detect_track as dt_mod
    from pipeline import faces as faces_mod
    from pipeline import occluders as occ_mod
    from pipeline import warmup as warmup_mod

    monkeypatch.setattr(warmup_mod, "_WARMED_INSTANCES", set())
    monkeypatch.setattr(warmup_mod, "_WARNED_MODELS", set())

    class _StubFaceApp:
        def get(self, img: Any) -> list[Any]:
            return []

    monkeypatch.setattr(dt_mod, "load_person_detector", lambda *a, **kw: object())
    monkeypatch.setattr(dt_mod, "get_device", lambda: "cpu")
    monkeypatch.setattr(dt_mod, "detect_persons", lambda frames, **kw: [[] for _ in frames])
    monkeypatch.setattr(faces_mod, "get_face_app", lambda: _StubFaceApp())
    monkeypatch.setattr(faces_mod, "get_active_provider", lambda: "CPUExecutionProvider")
    monkeypatch.setattr(occ_mod, "get_model", lambda *a, **kw: None)

    res = warmup_mod.warmup(include_critical=True)
    assert res.ok is True
    assert res.loaded == {"person_detector": True, "face_model": True, "clip": False}
    assert any("clip" in w.lower() for w in res.warnings)


def test_warmup_critical_failure_policy(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Critical failure warns (at most once) with include_critical=False and raises with include_critical=True."""
    from pipeline import detect_track as dt_mod
    from pipeline import faces as faces_mod
    from pipeline import occluders as occ_mod
    from pipeline import warmup as warmup_mod

    monkeypatch.setattr(warmup_mod, "_WARMED_INSTANCES", set())
    monkeypatch.setattr(warmup_mod, "_WARNED_MODELS", set())

    def _fail_detector(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("weights missing")

    class _StubFaceApp:
        def get(self, img: Any) -> list[Any]:
            return []

    monkeypatch.setattr(dt_mod, "load_person_detector", _fail_detector)
    monkeypatch.setattr(faces_mod, "get_face_app", lambda: _StubFaceApp())
    monkeypatch.setattr(faces_mod, "get_active_provider", lambda: "CPUExecutionProvider")
    monkeypatch.setattr(occ_mod, "get_model", lambda *a, **kw: {"stub": True})
    monkeypatch.setattr(occ_mod, "score_occluders_batch", lambda crops, **kw: ([], []))

    res1 = warmup_mod.warmup(include_critical=False, run_dummy=False)
    res2 = warmup_mod.warmup(include_critical=False, run_dummy=False)
    assert res1.ok is False
    assert res1.loaded["person_detector"] is False
    assert any("person detector" in w.lower() for w in res1.warnings)
    assert res2.ok is False

    out = capsys.readouterr().out
    assert out.count("[warmup] Warning: Person detector") == 1

    with pytest.raises(ModelLoadError):
        warmup_mod.warmup(include_critical=True, run_dummy=False)


def test_cached_getters_return_same_object_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Second calls to load_person_detector, get_face_app, and get_model reuse identical objects."""
    from pipeline import detect_track as dt_mod
    from pipeline import faces as faces_mod
    from pipeline import occluders as occ_mod

    # 1. Person detector cache
    monkeypatch.setattr(dt_mod, "_PERSON_DETECTORS", {})
    monkeypatch.setattr(dt_mod, "get_device", lambda: "cpu")

    class _FakeModel:
        def eval(self) -> None:
            pass

        def to(self, dev: str) -> None:
            pass

    det_counter = {"n": 0}
    import torchvision.models.detection as tv_det

    def _fake_frcnn(**kw: Any) -> _FakeModel:
        det_counter["n"] += 1
        return _FakeModel()

    monkeypatch.setattr(tv_det, "fasterrcnn_mobilenet_v3_large_320_fpn", _fake_frcnn)
    d1 = dt_mod.load_person_detector(device="cpu")
    d2 = dt_mod.load_person_detector(device="cpu")
    assert d1 is d2
    assert det_counter["n"] == 1

    # 2. Face app cache
    monkeypatch.setattr(faces_mod, "_FACE_APP", None)
    monkeypatch.setattr(faces_mod, "_ACTIVE_PROVIDER", None)
    monkeypatch.setattr(faces_mod, "_cuda_libraries_available", lambda *a: False)
    face_counter = {"n": 0}

    def _fake_init_face(provider: str) -> object:
        face_counter["n"] += 1
        return object()

    monkeypatch.setattr(faces_mod, "_init_face_analysis", _fake_init_face)
    f1 = faces_mod.get_face_app()
    f2 = faces_mod.get_face_app()
    assert f1 is f2
    assert face_counter["n"] == 1

    # 3. CLIP model cache
    monkeypatch.setattr(occ_mod, "_CLIP_BUNDLE", None)
    monkeypatch.setattr(occ_mod, "_CLIP_LOAD_FAILED", False)
    import open_clip
    import torch

    clip_counter = {"n": 0}

    class _FakeClip:
        def __init__(self) -> None:
            self.logit_scale = torch.tensor(1.0)

        def eval(self) -> None:
            pass

    monkeypatch.setattr(
        open_clip,
        "create_model_and_transforms",
        lambda *a, **kw: (clip_counter.__setitem__("n", clip_counter["n"] + 1) or _FakeClip(), None, lambda x: x),
    )
    monkeypatch.setattr(open_clip, "get_tokenizer", lambda *a: object())
    monkeypatch.setattr(occ_mod, "_encode_prompt_groups", lambda *a: {})
    c1 = occ_mod.get_model()
    c2 = occ_mod.get_model()
    assert c1 is c2
    assert clip_counter["n"] == 1
