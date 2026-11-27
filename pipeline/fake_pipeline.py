"""Lightweight fake pipeline for teammates without ML libraries installed.

Uses only Python stdlib, Pydantic, and Pillow (no torch, no cv2).
"""

import json
import math
from pathlib import Path
import random
import struct
from typing import Any, Callable
import zipfile

from PIL import Image, ImageDraw

from pipeline.contract import (
    Enhancement,
    IndexFace,
    IndexResult,
    IndexTrack,
    PipelineResult,
    SearchMatch,
    SearchResult,
    load_result,
)
from pipeline.errors import InvalidArgumentError, ZoneNotFoundError, validate_zone_polygon
from pipeline.link_transaction import load_zone


SAMPLE_RESULT_PATH = Path(__file__).resolve().parent.parent / "docs" / "sample_result.json"


def _emit(progress_cb: Callable[[dict[str, Any]], None] | None, stage: str, fraction: float, message: str) -> None:
    if progress_cb is None:
        return
    try:
        progress_cb({"stage": stage, "fraction": float(fraction), "message": message})
    except Exception:
        pass


def run(
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
) -> PipelineResult:
    """Return a validated PipelineResult from docs/sample_result.json.

    Accepts the same keyword arguments and validates arguments identically to
    pipeline.run_pipeline.run().
    """
    _ = (tracker, out_dir)
    if float(window_sec) <= 0.0:
        raise InvalidArgumentError(f"window_sec must be > 0, got {window_sec}")
    if float(sample_fps) <= 0.0:
        raise InvalidArgumentError(f"sample_fps must be > 0, got {sample_fps}")
    if float(tx_offset_sec) < 0.0:
        raise InvalidArgumentError(f"tx_offset_sec must be >= 0, got {tx_offset_sec}")

    if zone_polygon_norm is not None:
        validate_zone_polygon(zone_polygon_norm)
    elif atm_id:
        try:
            load_zone(atm_id)
        except KeyError as exc:
            raise ZoneNotFoundError(str(exc)) from exc

    _emit(progress_cb, "frames", 0.1, "Sampling frames (fake)")
    _emit(progress_cb, "detect_persons", 0.4, "Detecting persons (fake)")
    _emit(progress_cb, "faces", 0.7, "Detecting faces (fake)")
    _emit(progress_cb, "save", 0.95, "Saving results (fake)")

    result = load_result(SAMPLE_RESULT_PATH)
    clip_id = Path(clip_path).stem or result.clip_id
    updates: dict[str, object] = {"clip_id": clip_id, "link_low_margin": False}
    if transaction_time is not None:
        updates["transaction_time"] = transaction_time

    _emit(progress_cb, "done", 1.0, "Done (fake)")
    return result.model_copy(update=updates)


def fake_enhance(
    image_path: str | Path,
    crop_box: list[int] | tuple[int, int, int, int],
    scale: int = 4,
    out_dir: str | Path | None = None,
) -> Enhancement:
    """Crop and Lanczos-upscale an image with Pillow, stamping 'ENHANCED x<scale>' in pixels.

    Saves next to the original (or in out_dir) as <name>_enh_x<scale>.jpg without
    modifying the original, and returns an Enhancement matching enhance_frame().
    """
    if scale not in (2, 4):
        raise ValueError(f"scale must be 2 or 4, got {scale}")

    src = Path(image_path)
    target_dir = Path(out_dir) if out_dir is not None else src.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"{src.stem}_enh_x{scale}.jpg"

    with Image.open(src) as img:
        img_w, img_h = img.size
        x, y, w, h = [int(v) for v in crop_box]
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(img_w, x + w)
        y2 = min(img_h, y + h)
        cw, ch = x2 - x1, y2 - y1
        if cw < 8 or ch < 8:
            raise ValueError(f"Clipped crop_box [{x1}, {y1}, {cw}, {ch}] is too small")

        cropped = img.convert("RGB").crop((x1, y1, x2, y2))
        upscaled = cropped.resize(
            (cw * scale, ch * scale),
            resample=Image.Resampling.LANCZOS,
        )
        banner_h = max(20, int(round(upscaled.width * 0.12)))
        canvas = Image.new("RGB", (upscaled.width, upscaled.height + banner_h), color=(220, 0, 0))
        canvas.paste(upscaled, (0, banner_h))
        draw = ImageDraw.Draw(canvas)
        draw.text((6, max(2, banner_h // 2 - 6)), f"ENHANCED x{scale}", fill=(255, 255, 255))
        canvas.save(out_path, format="JPEG", quality=95)

    return Enhancement(
        enhanced_path=str(out_path),
        method="lanczos",
        scale=scale,
        model_version="lanczos_v1",
        crop_box=[x1, y1, cw, ch],
        search_embedding_source="original",
    )


def _npy_bytes(shape: tuple[int, ...], descr: str, payload: bytes) -> bytes:
    """Serialize a minimal NumPy .npy v1.0 buffer using stdlib only."""
    shape_str = f"({shape[0]},)" if len(shape) == 1 else f"({', '.join(str(d) for d in shape)})"
    header = f"{{'descr': '{descr}', 'fortran_order': False, 'shape': {shape_str}, }}"
    pad_len = (64 - ((10 + len(header) + 1) % 64)) % 64
    header_bytes = (header + (" " * pad_len) + "\n").encode("latin1")
    return b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header_bytes)) + header_bytes + payload


def _unit_vec_512(rng: random.Random) -> list[float]:
    raw = [rng.gauss(0.0, 1.0) for _ in range(512)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


def index_clip(
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
) -> IndexResult:
    """Fake index_clip returning 3 seeded tracks and writing valid index.npz/index.json."""
    _ = (tracker, min_face_px)
    if float(start_sec) < 0.0:
        raise InvalidArgumentError(f"start_sec must be >= 0, got {start_sec}")
    if float(sample_fps) <= 0.0:
        raise InvalidArgumentError(f"sample_fps must be > 0, got {sample_fps}")
    if int(faces_per_track) <= 0:
        raise InvalidArgumentError(f"faces_per_track must be > 0, got {faces_per_track}")
    if float(max_seconds) <= 0.0:
        raise InvalidArgumentError(f"max_seconds must be > 0, got {max_seconds}")

    has_zone = False
    if zone_polygon_norm is not None:
        validate_zone_polygon(zone_polygon_norm)
        has_zone = True
    elif atm_id:
        try:
            load_zone(atm_id)
            has_zone = True
        except KeyError as exc:
            raise ZoneNotFoundError(str(exc)) from exc

    actual_end = float(start_sec) + 30.0 if end_sec is None else float(end_sec)
    if actual_end <= float(start_sec):
        raise InvalidArgumentError(f"end_sec ({actual_end}) must be > start_sec ({start_sec})")
    if (actual_end - float(start_sec)) > float(max_seconds):
        raise InvalidArgumentError(f"Requested range exceeds max_seconds={max_seconds}")

    _emit(progress_cb, "frames", 0.1, "Streaming frames (fake)")
    _emit(progress_cb, "detect_persons", 0.4, "Detecting persons (fake)")
    _emit(progress_cb, "faces", 0.7, "Extracting faces (fake)")

    clip_id = Path(clip_path).stem or "fake_clip"
    s_lbl = f"{float(start_sec):g}".replace(".", "p")
    e_lbl = f"{actual_end:g}".replace(".", "p")
    index_dir = Path(out_dir) / clip_id / f"index_s{s_lbl}_e{e_lbl}"
    index_dir.mkdir(parents=True, exist_ok=True)
    npz_path = index_dir / "index.npz"
    json_path = index_dir / "index.json"

    rng = random.Random(42)
    tracks: list[IndexTrack] = []
    all_vecs: list[list[float]] = []
    all_meta: list[dict[str, Any]] = []

    for tid in (1, 2, 3):
        t0 = round(float(start_sec) + (tid - 1) * 5.0, 3)
        t1 = round(min(actual_end, t0 + 8.0), 3)
        faces: list[IndexFace] = []
        n_faces = min(int(faces_per_track), 2 if tid < 3 else 1)
        for j in range(n_faces):
            ft = round(min(t1, t0 + j * 1.5), 3)
            tms = f"{int(round(ft * 1000.0)):06d}"
            frame_p = index_dir / f"track{tid}_frame_{tms}.jpg"
            crop_p = index_dir / f"track{tid}_crop_{tms}.jpg"
            emb_p = index_dir / f"track{tid}_emb_{tms}.npy"

            Image.new("RGB", (64, 64), color=(80, 100, 120)).save(frame_p, format="JPEG")
            Image.new("RGB", (32, 32), color=(120, 120, 140)).save(crop_p, format="JPEG")
            vec = _unit_vec_512(rng)
            emb_p.write_bytes(_npy_bytes((512,), "<f4", struct.pack("<512f", *vec)))

            q_score = round(0.85 - j * 0.1 - (tid - 1) * 0.05, 3)
            face_box = [10.0, 10.0, 74.0, 74.0]
            faces.append(
                IndexFace(
                    t=ft,
                    quality_score=q_score,
                    reliability="High" if q_score >= 0.7 else "Medium",
                    match_ready=True,
                    flags=[],
                    face_box=face_box,
                    crop_path=str(crop_p),
                    frame_path=str(frame_p),
                    embedding_path=str(emb_p),
                )
            )
            all_vecs.append(vec)
            all_meta.append(
                {
                    "track_id": tid,
                    "t": ft,
                    "quality_score": q_score,
                    "reliability": "High" if q_score >= 0.7 else "Medium",
                    "match_ready": True,
                    "flags": [],
                    "face_box": face_box,
                    "crop_path": str(crop_p),
                    "frame_path": str(frame_p),
                    "embedding_path": str(emb_p),
                }
            )

        n_obs = max(2, len(faces) * 3)
        tracks.append(
            IndexTrack(
                track_id=tid,
                first_t=t0,
                last_t=t1,
                n_observations=n_obs,
                short_track=n_obs < 2,
                dwell_sec_in_zone=round(t1 - t0, 3) if has_zone else None,
                faces=faces,
                reason=None,
            )
        )

    _emit(progress_cb, "save", 0.95, "Writing index.npz and index.json (fake)")
    flat = [x for v in all_vecs for x in v]
    emb_npy = _npy_bytes((len(all_vecs), 512), "<f4", struct.pack(f"<{len(flat)}f", *flat))
    meta_bytes = json.dumps(all_meta).encode("utf-8")
    meta_npy = _npy_bytes((), f"|S{max(1, len(meta_bytes))}", meta_bytes or b"\x00")
    with zipfile.ZipFile(npz_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("embeddings.npy", emb_npy)
        zf.writestr("metadata_json.npy", meta_npy)

    res = IndexResult(
        clip_id=clip_id,
        start_sec=round(float(start_sec), 3),
        end_sec=round(actual_end, 3),
        tracks=tracks,
        index_npz_path=str(npz_path),
        index_json_path=str(json_path),
        total_embeddings=len(all_vecs),
        timings_ms={"frames": 1.0, "detect_persons": 1.0, "track": 1.0, "faces": 1.0, "quality": 1.0, "save": 1.0},
    )
    json_path.write_text(res.model_dump_json(indent=2), encoding="utf-8")
    _emit(progress_cb, "done", 1.0, "Done (fake)")
    return res


def search_with_enhancement(
    index_dir: str | Path,
    original_crop_path: str | Path | None,
    enhanced_crop_path: str | Path | None = None,
    exclude_track: int | None = None,
    top_k: int | None = None,
    original_embedding: Any | None = None,
    enhanced_embedding: Any | None = None,
) -> SearchResult:
    """Fake search_with_enhancement returning seeded SearchResult with no heavy imports."""
    _ = (index_dir, original_crop_path, original_embedding, enhanced_embedding)
    rng = random.Random(7)
    k = int(top_k if top_k is not None else 5)
    has_enh = enhanced_crop_path is not None

    matches: list[SearchMatch] = []
    for tid in range(1, min(k, 3) + 1):
        if exclude_track is not None and tid == int(exclude_track):
            continue
        sim = round(0.82 - (tid - 1) * 0.14 + rng.uniform(-0.02, 0.02), 4)
        sim_sec = round(sim - 0.04, 4) if has_enh else None
        delta = round(abs(sim - sim_sec), 4) if sim_sec is not None else None
        matches.append(
            SearchMatch(
                track_id=tid,
                t=round(10.0 + tid * 5.0, 2),
                similarity=sim,
                similarity_secondary=sim_sec,
                delta=delta,
                warning=None,
                crop_path=f"fake_track{tid}_crop.jpg",
                reliability="Medium",
                match_ready=True,
            )
        )

    return SearchResult(
        basis="original",
        banner="Possible leads only. A person must verify.",
        reliability_note=None,
        top_level_warning=None,
        reason=None,
        matches=matches,
    )


