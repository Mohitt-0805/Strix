"""Face detection and embedding extraction for Strix.

Heavy ML libraries (insightface, onnxruntime, cv2, numpy) are imported inside
functions only so lightweight modules can import pipeline.faces without them.
"""

from dataclasses import dataclass
from typing import Any


_FACE_APP: Any | None = None
_ACTIVE_PROVIDER: str | None = None


@dataclass
class FaceObs:
    """Face detection and embedding result for one person track observation."""

    t: float
    face_found: bool
    face_box: list[float] | None
    det_score: float | None
    landmarks: list[list[float]] | None
    yaw: float | None
    pitch: float | None
    roll: float | None
    yaw_lm: float | None
    face_width_px: float | None
    embedding: Any | None
    person_box: list[float]
    reason: str | None = None


def get_active_provider() -> str | None:
    """Return the ONNX Runtime provider currently used by the cached face app."""
    return _ACTIVE_PROVIDER


def _select_providers(available: list[str]) -> list[str]:
    """Filter available ORT providers to CUDA and CPU only (never TensorRT)."""
    allowed = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    selected = [p for p in allowed if p in available]
    return selected or ["CPUExecutionProvider"]


def _cuda_libraries_available(ort_mod: Any) -> bool:
    """Probe whether ORT CUDAExecutionProvider and required CUDA 13 libs are loadable."""
    if "CUDAExecutionProvider" not in ort_mod.get_available_providers():
        return False
    import ctypes

    try:
        ctypes.CDLL("libcublasLt.so.13")
        ctypes.CDLL("libcudart.so.13")
        return True
    except OSError:
        return False


def _resolve_insightface_root() -> str:
    """Resolve InsightFace root from MODEL_DIR (default data/models), with ~/.insightface fallback."""
    import os
    from pathlib import Path

    model_dir = Path(os.environ.get("MODEL_DIR", "data/models"))
    target_models = model_dir / "models" / "buffalo_l"
    if target_models.is_dir() and any(target_models.glob("*.onnx")):
        return str(model_dir)

    legacy_models = Path("~/.insightface").expanduser() / "models" / "buffalo_l"
    if legacy_models.is_dir() and any(legacy_models.glob("*.onnx")):
        return "~/.insightface"

    model_dir.mkdir(parents=True, exist_ok=True)
    return str(model_dir)


def _init_face_analysis(provider: str) -> Any:
    """Instantiate and prepare InsightFace buffalo_l for a single provider."""
    from insightface.app import FaceAnalysis

    ctx_id = 0 if provider == "CUDAExecutionProvider" else -1
    root = _resolve_insightface_root()
    app = FaceAnalysis(name="buffalo_l", root=root, providers=[provider])
    app.prepare(ctx_id=ctx_id, det_size=(640, 640))
    return app


def get_face_app() -> Any:
    """Load and cache InsightFace buffalo_l with CUDA -> CPU fallback."""
    global _FACE_APP, _ACTIVE_PROVIDER
    if _FACE_APP is not None:
        return _FACE_APP

    import warnings
    import onnxruntime as ort

    ort.set_default_logger_severity(3)
    warnings.filterwarnings(
        "ignore",
        message=r".*SimilarityTransform\.from_estimate.*",
        category=FutureWarning,
    )

    if _cuda_libraries_available(ort):
        try:
            app = _init_face_analysis("CUDAExecutionProvider")
            session_providers = app.det_model.session.get_providers()
            if "CUDAExecutionProvider" in session_providers:
                _FACE_APP = app
                _ACTIVE_PROVIDER = "CUDAExecutionProvider"
                print(f"[faces] InsightFace provider: {_ACTIVE_PROVIDER}")
                return _FACE_APP
            print(
                "[faces] Warning: CUDAExecutionProvider unavailable at runtime "
                f"(active: {session_providers}); falling back to CPUExecutionProvider"
            )
            _FACE_APP = app
            _ACTIVE_PROVIDER = session_providers[0] if session_providers else "CPUExecutionProvider"
            print(f"[faces] InsightFace provider: {_ACTIVE_PROVIDER}")
            return _FACE_APP
        except Exception as exc:
            print(f"[faces] Warning: CUDAExecutionProvider failed ({exc}); falling back to CPUExecutionProvider")
            _FACE_APP = _init_face_analysis("CPUExecutionProvider")
            _ACTIVE_PROVIDER = "CPUExecutionProvider"
            print(f"[faces] InsightFace provider: {_ACTIVE_PROVIDER}")
            return _FACE_APP

    print("[faces] CUDA libraries not found, using CPU (about 0.3 s per face)")
    _FACE_APP = _init_face_analysis("CPUExecutionProvider")
    _ACTIVE_PROVIDER = "CPUExecutionProvider"
    return _FACE_APP


def _empty_face_obs(t: float, person_box: list[float], reason: str | None = None) -> FaceObs:
    """Build a FaceObs representing an observation with no detected face."""
    return FaceObs(
        t=t,
        face_found=False,
        face_box=None,
        det_score=None,
        landmarks=None,
        yaw=None,
        pitch=None,
        roll=None,
        yaw_lm=None,
        face_width_px=None,
        embedding=None,
        person_box=person_box,
        reason=reason,
    )


def box_iou(box_a: list[float], box_b: list[float]) -> float:
    """Compute IoU between two [x1, y1, x2, y2] boxes."""
    ax1, ay1, ax2, ay2 = [float(v) for v in box_a]
    bx1, by1, bx2, by2 = [float(v) for v in box_b]
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0.0 else 0.0


def _box_containment(inner_box: list[float], outer_box: list[float]) -> float:
    """Return fraction of inner_box area lying inside outer_box."""
    ix1, iy1, ix2, iy2 = [float(v) for v in inner_box]
    ox1, oy1, ox2, oy2 = [float(v) for v in outer_box]
    inner_area = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inner_area <= 0.0:
        return 0.0
    inter_w = max(0.0, min(ix2, ox2) - max(ix1, ox1))
    inter_h = max(0.0, min(iy2, oy2) - max(iy1, oy1))
    return (inter_w * inter_h) / inner_area


def _head_region_metrics(face_box: list[float], person_box: list[float]) -> tuple[float, float] | None:
    """Return (containment, height_score) if face centre is in upper 45% of person_box, else None."""
    fx1, fy1, fx2, fy2 = [float(v) for v in face_box]
    px1, py1, px2, py2 = [float(v) for v in person_box]
    ph = py2 - py1
    if ph <= 0.0 or px2 <= px1:
        return None
    fcx = 0.5 * (fx1 + fx2)
    fcy = 0.5 * (fy1 + fy2)
    if not (px1 <= fcx <= px2 and py1 <= fcy <= py1 + 0.45 * ph):
        return None
    containment = _box_containment(face_box, person_box)
    height_score = 1.0 - ((fcy - py1) / ph)
    return containment, height_score


def select_face_for_person_box(
    candidates: list[tuple[Any, list[float], float]],
    person_box: list[float],
) -> tuple[Any | None, str | None]:
    """Pick the best face candidate whose centre is in the upper 45% of person_box.

    candidates is a list of (face_obj, full_frame_face_box, det_score).
    Scores qualifying candidates by det_score * containment.
    """
    if not candidates:
        return None, None

    best_obj: Any | None = None
    best_score = -1.0
    for obj, fbox, det_score in candidates:
        metrics = _head_region_metrics(fbox, person_box)
        if metrics is None:
            continue
        containment, _ = metrics
        score = float(det_score) * containment
        if score > best_score:
            best_score = score
            best_obj = obj

    if best_obj is None:
        return None, "no face in head region"
    return best_obj, None


def assign_faces_to_tracks(
    observations_at_t: dict[int, FaceObs],
    iou_thresh: float = 0.5,
) -> dict[int, FaceObs]:
    """Ensure each detected face at timestamp t is assigned to at most one track."""
    claimed: list[tuple[float, float, int, FaceObs]] = []
    out: dict[int, FaceObs] = {}

    for tid, obs in observations_at_t.items():
        if not obs.face_found or obs.face_box is None:
            out[tid] = obs
            continue
        hm = _head_region_metrics(obs.face_box, obs.person_box)
        if hm is not None:
            containment, height_score = hm
        else:
            containment = _box_containment(obs.face_box, obs.person_box)
            px1, py1, px2, py2 = [float(v) for v in obs.person_box]
            fcy = 0.5 * (obs.face_box[1] + obs.face_box[3])
            height_score = 1.0 - ((fcy - py1) / max(1e-6, py2 - py1))
        claimed.append((round(containment, 4), height_score, tid, obs))

    claimed.sort(key=lambda item: (item[0], item[1], -item[2]), reverse=True)
    kept_boxes: list[list[float]] = []

    for _, _, tid, obs in claimed:
        assert obs.face_box is not None
        if any(box_iou(obs.face_box, kb) > iou_thresh for kb in kept_boxes):
            out[tid] = _empty_face_obs(obs.t, obs.person_box, reason="face shared with another person")
        else:
            kept_boxes.append(obs.face_box)
            out[tid] = obs

    return out


def _lookup_frame(frames_by_time: dict[float, Any], t: float) -> Any | None:
    """Look up a frame by exact or rounded timestamp."""
    frame = frames_by_time.get(t)
    if frame is not None:
        return frame
    rounded = round(t, 6)
    for k, v in frames_by_time.items():
        if round(float(k), 6) == rounded:
            return v
    return None


def estimate_yaw_from_landmarks(landmarks: list[list[float]] | None) -> float | None:
    """Estimate yaw in [-90, 90] degrees from 5-point landmarks (nose vs eyes)."""
    if landmarks is None or len(landmarks) < 3:
        return None
    left_eye_x = float(landmarks[0][0])
    right_eye_x = float(landmarks[1][0])
    nose_x = float(landmarks[2][0])

    eye_span = abs(right_eye_x - left_eye_x)
    if eye_span < 1e-6:
        return None

    eye_mid_x = 0.5 * (left_eye_x + right_eye_x)
    ratio = (nose_x - eye_mid_x) / (0.5 * eye_span)
    clamped = max(-1.0, min(1.0, ratio))
    return float(clamped * 90.0)


def _extract_normed_embedding(face: Any, np_mod: Any) -> Any | None:
    """Return an L2-normalised float32 512-d embedding from a Face object."""
    emb = getattr(face, "normed_embedding", None)
    if emb is None:
        raw = getattr(face, "embedding", None)
        if raw is None:
            return None
        vec = np_mod.asarray(raw, dtype=np_mod.float32)
        norm = float(np_mod.linalg.norm(vec))
        return vec / norm if norm > 0.0 else vec
    vec = np_mod.asarray(emb, dtype=np_mod.float32)
    norm = float(np_mod.linalg.norm(vec))
    return vec / norm if norm > 0.0 else vec


def detect_faces_on_track(
    track: Any,
    frames_by_time: dict[float, Any],
    margin: float = 0.15,
) -> list[FaceObs]:
    """Detect the highest-scoring face in each observation of a person track."""
    import numpy as np

    app = get_face_app()
    results: list[FaceObs] = []

    for obs in getattr(track, "observations", []):
        t = float(obs["t"])
        person_box = [float(v) for v in obs["box"]]
        frame = _lookup_frame(frames_by_time, t)
        if frame is None or getattr(frame, "size", 0) == 0:
            results.append(_empty_face_obs(t, person_box))
            continue

        h, w = frame.shape[:2]
        x1, y1, x2, y2 = person_box
        pad_x = max(0.0, (x2 - x1) * margin)
        pad_y = max(0.0, (y2 - y1) * margin)

        cx1 = max(0, int(np.floor(x1 - pad_x)))
        cy1 = max(0, int(np.floor(y1 - pad_y)))
        cx2 = min(w, int(np.ceil(x2 + pad_x)))
        cy2 = min(h, int(np.ceil(y2 + pad_y)))

        if cx2 - cx1 < 2 or cy2 - cy1 < 2:
            results.append(_empty_face_obs(t, person_box))
            continue

        crop = frame[cy1:cy2, cx1:cx2]
        if crop.size == 0:
            results.append(_empty_face_obs(t, person_box))
            continue

        faces = app.get(crop)
        if not faces:
            results.append(_empty_face_obs(t, person_box))
            continue

        candidates = [
            (
                f,
                [
                    float(f.bbox[0]) + cx1,
                    float(f.bbox[1]) + cy1,
                    float(f.bbox[2]) + cx1,
                    float(f.bbox[3]) + cy1,
                ],
                float(getattr(f, "det_score", 0.0) or 0.0),
            )
            for f in faces
        ]
        best, reject_reason = select_face_for_person_box(candidates, person_box)
        if best is None:
            results.append(_empty_face_obs(t, person_box, reason=reject_reason))
            continue

        bx1, by1, bx2, by2 = [float(v) for v in best.bbox]
        face_box = [bx1 + cx1, by1 + cy1, bx2 + cx1, by2 + cy1]
        face_width_px = float(max(0.0, face_box[2] - face_box[0]))

        landmarks: list[list[float]] | None = None
        if getattr(best, "kps", None) is not None:
            landmarks = [[float(pt[0]) + cx1, float(pt[1]) + cy1] for pt in best.kps]

        pose = getattr(best, "pose", None)
        if pose is not None and len(pose) >= 3:
            # InsightFace Landmark.get (insightface/model_zoo/landmark.py) and
            # transform.matrix2angle return face.pose as [pitch, yaw, roll] in degrees.
            pitch = float(pose[0])
            yaw = float(pose[1])
            roll = float(pose[2])
        else:
            pitch = yaw = roll = None

        yaw_lm = estimate_yaw_from_landmarks(landmarks)
        embedding = _extract_normed_embedding(best, np)
        results.append(
            FaceObs(
                t=t,
                face_found=True,
                face_box=face_box,
                det_score=float(best.det_score),
                landmarks=landmarks,
                yaw=yaw,
                pitch=pitch,
                roll=roll,
                yaw_lm=yaw_lm,
                face_width_px=face_width_px,
                embedding=embedding,
                person_box=person_box,
            )
        )

    return results
