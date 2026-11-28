"""Person detection and tracking for Strix.

Heavy ML libraries (torch, torchvision, cv2, supervision, scipy) are imported
inside functions/classes only so teammates without ML packages can still import
lightweight pipeline modules.
"""

from dataclasses import dataclass, field
import threading
from typing import Any, Iterable, Literal


COCO_PERSON_CLASS_ID = 1
_DETECTOR_LOCK = threading.Lock()
_PERSON_DETECTORS: dict[str, Any] = {}


@dataclass
class Track:
    """A tracked person across sampled video frames."""

    track_id: int
    observations: list[dict[str, Any]] = field(default_factory=list)

    @property
    def first_t(self) -> float:
        """Timestamp of the first observation in seconds."""
        return float(self.observations[0]["t"]) if self.observations else 0.0

    @property
    def last_t(self) -> float:
        """Timestamp of the last observation in seconds."""
        return float(self.observations[-1]["t"]) if self.observations else 0.0

    @property
    def duration(self) -> float:
        """Duration between first and last observation in seconds."""
        return self.last_t - self.first_t if self.observations else 0.0


def get_device() -> str:
    """Return 'cuda' if a CUDA GPU is available, otherwise 'cpu'."""
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def load_person_detector(device: str | None = None) -> Any:
    """Load and cache Faster R-CNN MobileNetV3 Large 320 FPN with default COCO weights."""
    import os
    from pathlib import Path
    import torch
    from torchvision.models.detection import (
        FasterRCNN_MobileNet_V3_Large_320_FPN_Weights,
        fasterrcnn_mobilenet_v3_large_320_fpn,
    )

    target_device = device or get_device()
    with _DETECTOR_LOCK:
        cached = _PERSON_DETECTORS.get(target_device)
        if cached is not None:
            return cached

        model_dir = Path(os.environ.get("MODEL_DIR", "data/models"))
        torch_dir = model_dir / "torch"
        legacy_dir = Path(torch.hub.get_dir())
        if torch_dir.is_dir() and any(torch_dir.iterdir()):
            torch.hub.set_dir(str(torch_dir))
        elif not (legacy_dir.is_dir() and any(legacy_dir.iterdir())):
            torch_dir.mkdir(parents=True, exist_ok=True)
            torch.hub.set_dir(str(torch_dir))

        weights = FasterRCNN_MobileNet_V3_Large_320_FPN_Weights.DEFAULT
        model = fasterrcnn_mobilenet_v3_large_320_fpn(weights=weights)
        model.eval()
        model.to(target_device)
        _PERSON_DETECTORS[target_device] = model
        return model


def _bgr_to_tensor(frame: Any, cv2_mod: Any, torch_mod: Any) -> Any:
    """Convert a BGR uint8 ndarray to a normalized float32 CHW tensor in [0, 1]."""
    rgb = cv2_mod.cvtColor(frame, cv2_mod.COLOR_BGR2RGB)
    return torch_mod.from_numpy(rgb).permute(2, 0, 1).contiguous().float() / 255.0


def _filter_person_detections(outputs: dict[str, Any], score_thresh: float) -> list[dict[str, Any]]:
    """Keep only COCO class 1 (person) detections above score_thresh."""
    boxes = outputs["boxes"].detach().cpu().tolist()
    labels = outputs["labels"].detach().cpu().tolist()
    scores = outputs["scores"].detach().cpu().tolist()

    detections: list[dict[str, Any]] = []
    for box, label, score in zip(boxes, labels, scores):
        if int(label) == COCO_PERSON_CLASS_ID and float(score) >= score_thresh:
            detections.append(
                {
                    "box": [float(box[0]), float(box[1]), float(box[2]), float(box[3])],
                    "score": float(score),
                }
            )
    return detections


def detect_persons(
    frames: list[Any],
    score_thresh: float = 0.5,
    model: Any | None = None,
    device: str | None = None,
) -> list[list[dict[str, Any]]]:
    """Run person detection one frame at a time with CUDA OOM fallback to CPU.

    Args:
        frames: Sequence of BGR uint8 numpy arrays.
        score_thresh: Minimum confidence score to keep a person detection.
        model: Optional preloaded Faster R-CNN model.
        device: Optional device override ('cuda' or 'cpu').

    Returns:
        Per-frame list of dicts: {'box': [x1, y1, x2, y2], 'score': float}.
    """
    import cv2
    import torch

    detector = model if model is not None else load_person_detector(device=device)
    active_device = str(next(detector.parameters()).device)
    results: list[list[dict[str, Any]]] = []

    with torch.no_grad():
        for frame in frames:
            tensor = _bgr_to_tensor(frame, cv2, torch)
            try:
                outputs = detector([tensor.to(active_device)])[0]
            except RuntimeError as exc:
                is_oom = isinstance(exc, torch.cuda.OutOfMemoryError) or (
                    "out of memory" in str(exc).lower()
                )
                if not is_oom or not active_device.startswith("cuda"):
                    raise

                print("WARNING: CUDA out of memory; clearing cache and falling back to CPU.")
                torch.cuda.empty_cache()
                active_device = "cpu"
                detector.to("cpu")
                with _DETECTOR_LOCK:
                    if _PERSON_DETECTORS.get("cuda") is detector:
                        _PERSON_DETECTORS.pop("cuda", None)
                        _PERSON_DETECTORS["cpu"] = detector
                outputs = detector([tensor.to("cpu")])[0]

            results.append(_filter_person_detections(outputs, score_thresh))

    return results


def _compute_iou_matrix(boxes_a: list[list[float]], boxes_b: list[list[float]]) -> Any:
    """Compute pairwise IoU matrix (len(boxes_a), len(boxes_b)) using numpy."""
    import numpy as np

    a = np.asarray(boxes_a, dtype=np.float32)
    b = np.asarray(boxes_b, dtype=np.float32)

    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])

    inter = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    area_a = np.maximum(0.0, a[:, 2] - a[:, 0]) * np.maximum(0.0, a[:, 3] - a[:, 1])
    area_b = np.maximum(0.0, b[:, 2] - b[:, 0]) * np.maximum(0.0, b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return np.where(union > 0.0, inter / union, 0.0)


class IoUTracker:
    """Timestamp-aware IoU tracker using Hungarian assignment (scipy)."""

    def __init__(self, iou_thresh: float = 0.3, max_gap_sec: float = 2.0) -> None:
        self.iou_thresh = iou_thresh
        self.max_gap_sec = max_gap_sec
        self._next_id = 1
        self._active: dict[int, Track] = {}
        self._finished: list[Track] = []

    def _expire_stale_tracks(self, timestamp_sec: float) -> None:
        """Move tracks whose gap exceeds max_gap_sec out of active tracks."""
        expired_ids = [
            tid
            for tid, tr in self._active.items()
            if (timestamp_sec - tr.last_t) > self.max_gap_sec
        ]
        for tid in expired_ids:
            self._finished.append(self._active.pop(tid))

    def update(
        self, timestamp_sec: float, detections: list[dict[str, Any]]
    ) -> list[tuple[int, dict[str, Any]]]:
        """Match detections to active tracks by IoU and return (track_id, det) pairs."""
        from scipy.optimize import linear_sum_assignment

        self._expire_stale_tracks(timestamp_sec)
        assignments: list[tuple[int, dict[str, Any]]] = []
        matched_det_indices: set[int] = set()

        if self._active and detections:
            active_ids = list(self._active.keys())
            track_boxes = [self._active[tid].observations[-1]["box"] for tid in active_ids]
            det_boxes = [d["box"] for d in detections]

            iou_mat = _compute_iou_matrix(track_boxes, det_boxes)
            row_ind, col_ind = linear_sum_assignment(-iou_mat)

            for r, c in zip(row_ind, col_ind):
                if iou_mat[r, c] >= self.iou_thresh:
                    tid = active_ids[r]
                    det = detections[c]
                    self._active[tid].observations.append(
                        {"t": float(timestamp_sec), "box": list(det["box"]), "score": float(det["score"])}
                    )
                    assignments.append((tid, det))
                    matched_det_indices.add(c)

        for idx, det in enumerate(detections):
            if idx in matched_det_indices:
                continue
            tid = self._next_id
            self._next_id += 1
            self._active[tid] = Track(
                track_id=tid,
                observations=[
                    {"t": float(timestamp_sec), "box": list(det["box"]), "score": float(det["score"])}
                ],
            )
            assignments.append((tid, det))

        return assignments

    def finish(self) -> list[Track]:
        """Return all completed and active tracks sorted by track_id."""
        all_tracks = list(self._finished) + list(self._active.values())
        return sorted(all_tracks, key=lambda tr: tr.track_id)


class ByteTrackAdapter:
    """Adapter around supervision.ByteTrack (v0.25.1) matching IoUTracker's interface."""

    def __init__(
        self,
        frame_rate: int = 2,
        track_activation_threshold: float = 0.25,
        lost_track_buffer: int = 30,
        minimum_matching_threshold: float = 0.8,
        minimum_consecutive_frames: int = 1,
    ) -> None:
        import supervision as sv

        self._tracker = sv.ByteTrack(
            track_activation_threshold=track_activation_threshold,
            lost_track_buffer=lost_track_buffer,
            minimum_matching_threshold=minimum_matching_threshold,
            frame_rate=max(1, int(round(frame_rate))),
            minimum_consecutive_frames=minimum_consecutive_frames,
        )
        self._tracks: dict[int, Track] = {}

    def update(
        self, timestamp_sec: float, detections: list[dict[str, Any]]
    ) -> list[tuple[int, dict[str, Any]]]:
        """Update ByteTrack with detections and return (track_id, det) pairs."""
        import numpy as np
        import supervision as sv

        if detections:
            xyxy = np.asarray([d["box"] for d in detections], dtype=np.float32)
            conf = np.asarray([d["score"] for d in detections], dtype=np.float32)
            class_id = np.full(len(detections), COCO_PERSON_CLASS_ID, dtype=int)
            sv_dets = sv.Detections(xyxy=xyxy, confidence=conf, class_id=class_id)
        else:
            sv_dets = sv.Detections.empty()

        tracked = self._tracker.update_with_detections(sv_dets)
        assignments: list[tuple[int, dict[str, Any]]] = []
        if tracked.tracker_id is None:
            return assignments

        for box_arr, score_val, tid_val in zip(
            tracked.xyxy, tracked.confidence, tracked.tracker_id
        ):
            tid = int(tid_val)
            box = [float(v) for v in box_arr.tolist()]
            score = float(score_val)
            obs = {"t": float(timestamp_sec), "box": box, "score": score}
            if tid not in self._tracks:
                self._tracks[tid] = Track(track_id=tid, observations=[obs])
            else:
                self._tracks[tid].observations.append(obs)
            assignments.append((tid, {"box": box, "score": score}))

        return assignments

    def finish(self) -> list[Track]:
        """Return all tracks sorted by track_id."""
        return sorted(self._tracks.values(), key=lambda tr: tr.track_id)


def track_persons(
    frames_iter: Iterable[tuple[float, Any]],
    tracker: Literal["iou", "bytetrack"] = "iou",
    score_thresh: float = 0.5,
    sample_fps: float = 2.0,
    model: Any | None = None,
    device: str | None = None,
) -> list[Track]:
    """Run person detection and tracking over (timestamp_sec, frame) pairs."""
    detector = model if model is not None else load_person_detector(device=device)
    if tracker == "iou":
        tracker_obj: IoUTracker | ByteTrackAdapter = IoUTracker()
    elif tracker == "bytetrack":
        tracker_obj = ByteTrackAdapter(frame_rate=max(1, int(round(sample_fps))))
    else:
        raise ValueError(f"Unsupported tracker: {tracker!r}")

    for timestamp_sec, frame in frames_iter:
        dets = detect_persons([frame], score_thresh=score_thresh, model=detector)[0]
        tracker_obj.update(timestamp_sec, dets)

    return tracker_obj.finish()
