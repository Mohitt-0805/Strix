"""Model warmup utilities and CLI for Strix.

Heavy ML libraries (torch, cv2, insightface, onnxruntime, open_clip) are imported
inside functions only so lightweight modules can import pipeline.warmup without them.
"""

import argparse
import threading
import time
from typing import Any, Callable

from pipeline.contract import WarmupResult
from pipeline.errors import ModelLoadError


_WARMUP_LOCK = threading.Lock()
_WARMED_INSTANCES: set[tuple[str, int]] = set()
_WARNED_MODELS: set[str] = set()


def _emit_warmup(
    progress_cb: Callable[[dict[str, Any]], None] | None,
    fraction: float,
    message: str,
) -> None:
    """Safely send a monotonic warmup progress event."""
    if progress_cb is None:
        return
    try:
        progress_cb(
            {
                "stage": "warmup",
                "fraction": float(max(0.0, min(1.0, fraction))),
                "message": message,
            }
        )
    except Exception:
        pass


def _record_print_once(model_key: str, warning_text: str) -> None:
    """Print at most one warning line per failing model across calls."""
    if model_key not in _WARNED_MODELS:
        _WARNED_MODELS.add(model_key)
        print(f"[warmup] Warning: {warning_text}")


def _warm_person_detector(run_dummy: bool) -> tuple[bool, str | None, float, str | None, Exception | None]:
    """Load cached person detector and optionally run one synthetic 320x240 forward pass."""
    t0 = time.perf_counter()
    try:
        from pipeline.detect_track import detect_persons, get_device, load_person_detector

        detector = load_person_detector()
        try:
            device_str = str(next(detector.parameters()).device)
        except Exception:
            device_str = str(get_device())

        inst_key = ("person_detector", id(detector))
        if run_dummy and inst_key not in _WARMED_INSTANCES:
            import numpy as np

            dummy = np.zeros((240, 320, 3), dtype=np.uint8)
            detect_persons([dummy], model=detector)
            _WARMED_INSTANCES.add(inst_key)

        elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
        return True, device_str, elapsed, None, None
    except Exception as exc:
        elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
        warn_msg = f"Person detector failed to load: {exc}"
        _record_print_once("person_detector", warn_msg)
        return False, None, elapsed, warn_msg, exc


def _warm_face_model(run_dummy: bool) -> tuple[bool, str | None, float, str | None, Exception | None]:
    """Load cached InsightFace app and optionally run one synthetic 320x240 forward pass."""
    t0 = time.perf_counter()
    try:
        from pipeline.faces import get_active_provider, get_face_app

        app = get_face_app()
        inst_key = ("face_model", id(app))
        if run_dummy and inst_key not in _WARMED_INSTANCES:
            import numpy as np

            dummy = np.zeros((240, 320, 3), dtype=np.uint8)
            app.get(dummy)
            _WARMED_INSTANCES.add(inst_key)

        provider = get_active_provider()
        elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
        return True, provider, elapsed, None, None
    except Exception as exc:
        elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
        warn_msg = f"Face model failed to load: {exc}"
        _record_print_once("face_model", warn_msg)
        return False, None, elapsed, warn_msg, exc


def _warm_clip_model(include_clip: bool, run_dummy: bool) -> tuple[bool | None, float | None, str | None]:
    """Load cached CLIP model (if include_clip) and optionally run one synthetic pass."""
    if not include_clip:
        return None, None, None

    t0 = time.perf_counter()
    try:
        from pipeline.occluders import get_model, load_occluders_config, score_occluders_batch

        cfg = load_occluders_config()
        if not cfg.get("enabled", True):
            elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
            return None, elapsed, "CLIP occluder scoring is disabled in config"

        bundle = get_model(cfg)
        if bundle is None:
            elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
            # get_model() prints its own single warning line when failing.
            return False, elapsed, "CLIP model unavailable; occluder flags disabled"

        inst_key = ("clip", id(bundle))
        if run_dummy and inst_key not in _WARMED_INSTANCES:
            import numpy as np

            dummy = np.zeros((240, 320, 3), dtype=np.uint8)
            score_occluders_batch([dummy], cfg=cfg)
            _WARMED_INSTANCES.add(inst_key)

        elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
        return True, elapsed, None
    except Exception as exc:
        elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
        warn_msg = f"CLIP model unavailable ({exc}); occluder flags disabled"
        _record_print_once("clip", warn_msg)
        return False, elapsed, warn_msg


def warmup(
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    include_clip: bool = True,
    run_dummy: bool = True,
    include_critical: bool = False,
) -> WarmupResult:
    """Thread-safe, idempotent model loader and dummy-inference warmup.

    Person detector and face model are critical; CLIP is optional (failure disables
    occluder flags and adds a warning). Raises ModelLoadError only if a critical
    model fails and include_critical=True.
    """
    with _WARMUP_LOCK:
        total_t0 = time.perf_counter()
        warnings: list[str] = []

        _emit_warmup(progress_cb, 0.05, "Starting model warmup")

        _emit_warmup(progress_cb, 0.15, "Loading person detector")
        det_ok, torch_dev, det_ms, det_warn, det_exc = _warm_person_detector(run_dummy)
        if det_warn:
            warnings.append(det_warn)
        if not det_ok and include_critical:
            raise ModelLoadError(det_warn or "Person detector failed") from det_exc

        _emit_warmup(progress_cb, 0.45, "Loading face model")
        face_ok, face_prov, face_ms, face_warn, face_exc = _warm_face_model(run_dummy)
        if face_warn:
            warnings.append(face_warn)
        if not face_ok and include_critical:
            raise ModelLoadError(face_warn or "Face model failed") from face_exc

        _emit_warmup(
            progress_cb,
            0.75,
            "Loading CLIP occluder model" if include_clip else "Skipping CLIP occluder model",
        )
        clip_ok, clip_ms, clip_warn = _warm_clip_model(include_clip, run_dummy)
        if clip_warn:
            warnings.append(clip_warn)

        ok = bool(det_ok and face_ok)
        total_ms = round((time.perf_counter() - total_t0) * 1000.0, 2)
        _emit_warmup(progress_cb, 1.0, "Warmup complete" if ok else "Warmup finished with errors")

        return WarmupResult(
            ok=ok,
            loaded={
                "person_detector": det_ok,
                "face_model": face_ok,
                "clip": clip_ok,
            },
            providers={
                "faces": face_prov,
                "torch_device": torch_dev,
            },
            timings_ms={
                "person_detector": det_ms,
                "face_model": face_ms,
                "clip": clip_ms,
            },
            warnings=warnings,
            total_ms=total_ms,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Preload and warm up all Strix ML models.")
    parser.add_argument("--no-clip", action="store_true", help="Skip CLIP occluder model warmup")
    parser.add_argument("--no-dummy", action="store_true", help="Skip 320x240 dummy forward passes")
    parser.add_argument("--fail-on-critical", action="store_true", help="Exit non-zero if critical model fails")
    args = parser.parse_args()

    res = warmup(
        include_clip=not args.no_clip,
        run_dummy=not args.no_dummy,
        include_critical=False,
    )

    print(f"\n{'Model':<18}  {'Loaded':<8}  {'Timing (ms)':>11}")
    print("-" * 42)
    for key in ("person_detector", "face_model", "clip"):
        st = res.loaded.get(key)
        tm = res.timings_ms.get(key)
        st_str = "SKIP" if st is None else ("PASS" if st else "FAIL")
        tm_str = "-" if tm is None else f"{tm:.2f}"
        print(f"{key:<18}  {st_str:<8}  {tm_str:>11}")

    print(
        f"\nok={res.ok} | total_ms={res.total_ms:.2f} | "
        f"faces_provider={res.providers.get('faces')} | "
        f"torch_device={res.providers.get('torch_device')}"
    )
    for w in res.warnings:
        print(f"WARNING: {w}")

    return 0 if (res.ok or not args.fail_on_critical) else 1


if __name__ == "__main__":
    raise SystemExit(main())
