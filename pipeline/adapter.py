"""Adapter selecting fake, demo_pack cached, or real pipeline."""

import json
import os
from pathlib import Path
import time
from typing import Any, Callable


def _use_fake() -> bool:
    flag = os.environ.get("USE_FAKE_PIPELINE", "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def _demo_pack_dir() -> Path | None:
    raw = os.environ.get("DEMO_PACK_DIR", "").strip()
    if not raw:
        return None
    p = Path(raw)
    return p if (p / "manifest.json").exists() else None


def _replay_progress(progress_cb: Callable[[dict[str, Any]], None] | None, total_sec: float = 2.7) -> None:
    if progress_cb is None:
        return
    stages = [
        ("frames", 0.10, "Sampling frames (demo)"),
        ("detect_persons", 0.35, "Detecting persons (demo)"),
        ("track", 0.50, "Tracking persons (demo)"),
        ("link", 0.55, "Linking ATM zone (demo)"),
        ("faces", 0.75, "Detecting faces (demo)"),
        ("occluders", 0.85, "Checking occluders (demo)"),
        ("quality", 0.90, "Scoring face quality (demo)"),
        ("select", 0.95, "Selecting best frames (demo)"),
        ("done", 1.00, "Done (demo)"),
    ]
    delay = total_sec / len(stages)
    for stage, frac, msg in stages:
        time.sleep(delay)
        try:
            progress_cb({"stage": stage, "fraction": frac, "message": msg})
        except Exception:
            pass


def _resolve_pack_path(pack_dir: Path, p_str: str | None) -> str | None:
    if not p_str:
        return p_str
    p = Path(p_str)
    return str(p if p.is_absolute() else (pack_dir / p))


def get_run() -> Callable[..., object]:
    """Return fake, demo_pack cached, or real run()."""
    if _use_fake():
        from pipeline.fake_pipeline import run

        return run

    pack_dir = _demo_pack_dir()
    if pack_dir is None:
        from pipeline.run_pipeline import run

        return run

    def _cached_or_real_run(
        clip_path: str | Path,
        tx_offset_sec: float,
        window_sec: float = 10,
        atm_id: str = "",
        transaction_time: str | None = None,
        sample_fps: float = 2.0,
        tracker: str = "iou",
        out_dir: str | Path = "data/outputs",
        zone_polygon_norm: list[list[float]] | None = None,
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
    ) -> object:
        manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
        clip_name = Path(clip_path).name
        for entry in manifest.get("cases", []):
            if (
                entry.get("clip_name") == clip_name
                and str(entry.get("atm_id", "")) == str(atm_id)
                and abs(float(entry.get("tx_sec", -1)) - float(tx_offset_sec)) < 1e-6
                and abs(float(entry.get("window_sec", -1)) - float(window_sec)) < 1e-6
            ):
                from pipeline.contract import load_result

                print("[demo] served from demo_pack")
                _replay_progress(progress_cb)
                res = load_result(pack_dir / entry["result_json"])
                resolved_frames = []
                for fr in res.best_frames:
                    enh = (
                        fr.enhancement.model_copy(
                            update={"enhanced_path": _resolve_pack_path(pack_dir, fr.enhancement.enhanced_path)}
                        )
                        if fr.enhancement is not None
                        else None
                    )
                    resolved_frames.append(
                        fr.model_copy(
                            update={
                                "frame_path": _resolve_pack_path(pack_dir, fr.frame_path),
                                "embedding_path": _resolve_pack_path(pack_dir, fr.embedding_path),
                                "crop_path": _resolve_pack_path(pack_dir, fr.crop_path),
                                "enhancement": enh,
                            }
                        )
                    )
                updates: dict[str, Any] = {"best_frames": resolved_frames, "served_from_demo_pack": True}
                if transaction_time is not None:
                    updates["transaction_time"] = transaction_time
                return res.model_copy(update=updates)

        from pipeline.run_pipeline import run

        return run(
            clip_path=clip_path,
            tx_offset_sec=tx_offset_sec,
            window_sec=window_sec,
            atm_id=atm_id,
            transaction_time=transaction_time,
            sample_fps=sample_fps,
            tracker=tracker,
            out_dir=out_dir,
            zone_polygon_norm=zone_polygon_norm,
            progress_cb=progress_cb,
        )

    return _cached_or_real_run


def get_index_clip() -> Callable[..., object]:
    """Return fake, demo_pack cached, or real index_clip()."""
    if _use_fake():
        from pipeline.fake_pipeline import index_clip

        return index_clip

    pack_dir = _demo_pack_dir()
    if pack_dir is None:
        from pipeline.index_clip import index_clip

        return index_clip

    def _cached_or_real_index(
        clip_path: str | Path,
        start_sec: float = 0.0,
        end_sec: float | None = None,
        sample_fps: float = 1.0,
        tracker: str = "iou",
        faces_per_track: int = 3,
        min_face_px: int = 40,
        out_dir: str | Path = "data/outputs",
        zone_polygon_norm: list[list[float]] | None = None,
        atm_id: str | None = None,
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
        max_seconds: float = 600.0,
    ) -> object:
        manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
        clip_name = Path(clip_path).name
        for entry in manifest.get("indexes", []):
            if entry.get("clip_name") == clip_name:
                from pipeline.contract import IndexResult

                print("[demo] served from demo_pack")
                _replay_progress(progress_cb)
                idx_res = IndexResult.model_validate_json(
                    (pack_dir / entry["index_json"]).read_text(encoding="utf-8")
                )
                new_tracks = []
                for tr in idx_res.tracks:
                    new_faces = [
                        f.model_copy(
                            update={
                                "frame_path": _resolve_pack_path(pack_dir, f.frame_path),
                                "crop_path": _resolve_pack_path(pack_dir, f.crop_path),
                                "embedding_path": _resolve_pack_path(pack_dir, f.embedding_path),
                            }
                        )
                        for f in tr.faces
                    ]
                    new_tracks.append(tr.model_copy(update={"faces": new_faces}))
                return idx_res.model_copy(
                    update={
                        "tracks": new_tracks,
                        "index_json_path": str(pack_dir / entry["index_json"]),
                        "index_npz_path": str(pack_dir / entry["index_npz"]),
                        "served_from_demo_pack": True,
                    }
                )

        from pipeline.index_clip import index_clip

        return index_clip(
            clip_path=clip_path,
            start_sec=start_sec,
            end_sec=end_sec,
            sample_fps=sample_fps,
            tracker=tracker,
            faces_per_track=faces_per_track,
            min_face_px=min_face_px,
            out_dir=out_dir,
            zone_polygon_norm=zone_polygon_norm,
            atm_id=atm_id,
            progress_cb=progress_cb,
            max_seconds=max_seconds,
        )

    return _cached_or_real_index


def get_search() -> Callable[..., object]:
    """Return fake_pipeline.search_with_enhancement if USE_FAKE_PIPELINE is truthy, else compare.search_with_enhancement."""
    if _use_fake():
        from pipeline.fake_pipeline import search_with_enhancement

        return search_with_enhancement

    from pipeline.compare import search_with_enhancement

    return search_with_enhancement
