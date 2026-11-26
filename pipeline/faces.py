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


def _init_face_analysis(provider: str) -> Any:
    """Instantiate and prepare InsightFace buffalo_l for a single provider."""
    from insightface.app import FaceAnalysis

    ctx_id = 0 if provider == "CUDAExecutionProvider" else -1
    app = FaceAnalysis(name="buffalo_l", providers=[provider])
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


def _empty_face_obs(t: float, person_box: list[float]) -> FaceObs:
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
    )


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

        best = max(faces, key=lambda f: float(getattr(f, "det_score", 0.0) or 0.0))
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
