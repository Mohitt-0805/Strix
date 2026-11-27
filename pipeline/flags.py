"""Quality and pose flags for detected faces (pixels and pose only).

Heavy libraries (cv2, numpy) are imported inside functions only so lightweight
modules can import pipeline.flags without them.
"""

from typing import Any


def detect_occluders(face_crop: Any) -> list[str]:
    """Stub for semantic occluder detection.

    Cap, mask, and helmet flags will be added later using CLIP zero-shot.
    """
    _ = face_crop
    return []


def is_partial_face(
    face_obs: Any,
    frame_shape: tuple[int, ...],
    edge_margin_px: float = 2.0,
) -> bool:
    """Return True if the face box touches/exceeds the frame edge or person box."""
    if not getattr(face_obs, "face_found", False) or face_obs.face_box is None:
        return False

    h, w = frame_shape[:2]
    fx1, fy1, fx2, fy2 = [float(v) for v in face_obs.face_box]
    if fx1 <= edge_margin_px or fy1 <= edge_margin_px or fx2 >= (w - edge_margin_px) or fy2 >= (h - edge_margin_px):
        return True

    person_box = getattr(face_obs, "person_box", None)
    if person_box is not None and len(person_box) == 4:
        px1, py1, px2, py2 = [float(v) for v in person_box]
        # Flag if the face extends outside the person box (or touches its outer edge when non-zero).
        if fx1 < px1 - 1.0 or fy1 < py1 - 1.0 or fx2 > px2 + 1.0 or fy2 > py2 + 1.0:
            return True

    return False


def _luminance_region(
    face_obs: Any,
    frame_bgr: Any,
    crop_box: tuple[int, int, int, int],
) -> Any:
    """Return the eye-to-mouth region from 5 landmarks (with margin), or the full crop."""
    h, w = frame_bgr.shape[:2]
    cx1, cy1, cx2, cy2 = crop_box
    landmarks = getattr(face_obs, "landmarks", None)
    if landmarks is not None and len(landmarks) >= 5:
        xs = [float(pt[0]) for pt in landmarks[:5]]
        ys = [float(pt[1]) for pt in landmarks[:5]]
        lx1, lx2 = min(xs), max(xs)
        ly1, ly2 = min(ys), max(ys)
        pad_x = max(2.0, (lx2 - lx1) * 0.1)
        pad_y = max(2.0, (ly2 - ly1) * 0.1)
        rx1 = max(0, int(round(lx1 - pad_x)))
        ry1 = max(0, int(round(ly1 - pad_y)))
        rx2 = min(w, int(round(lx2 + pad_x)))
        ry2 = min(h, int(round(ly2 + pad_y)))
        if rx2 > rx1 and ry2 > ry1:
            return frame_bgr[ry1:ry2, rx1:rx2]
    return frame_bgr[cy1:cy2, cx1:cx2]


def compute_flags(
    face_obs: Any,
    frame_bgr: Any,
    metrics: Any,
    cfg: dict[str, Any],
    other_person_boxes: list[list[float]] | None = None,
) -> list[str]:
    """Compute descriptive quality/pose flags from pixels and pose only."""
    if not getattr(face_obs, "face_found", False) or face_obs.face_box is None:
        return []

    import cv2
    import numpy as np

    flag_cfg = cfg["flags"]
    occ_cfg = cfg["occlusion"]
    flags: list[str] = []

    h, w = frame_bgr.shape[:2]
    fx1, fy1, fx2, fy2 = face_obs.face_box
    cx1 = max(0, int(round(fx1)))
    cy1 = max(0, int(round(fy1)))
    cx2 = min(w, int(round(fx2)))
    cy2 = min(h, int(round(fy2)))

    if cx2 > cx1 and cy2 > cy1:
        crop = frame_bgr[cy1:cy2, cx1:cx2]
        lum_region = _luminance_region(face_obs, frame_bgr, (cx1, cy1, cx2, cy2))
        gray = cv2.cvtColor(lum_region, cv2.COLOR_BGR2GRAY)
        mean_lum = float(np.mean(gray))
        if mean_lum < float(flag_cfg["low_light_mean_thresh"]):
            flags.append("low light")
        flags.extend(detect_occluders(crop))

    if float(metrics.sharpness) < float(flag_cfg["blur_sharpness_thresh"]):
        flags.append("blur")

    if is_partial_face(face_obs, frame_bgr.shape, float(occ_cfg["edge_margin_px"])):
        flags.append("partial face")

    width_px = float(face_obs.face_width_px or 0.0)
    if width_px < float(flag_cfg["small_face_px"]):
        flags.append("small face")

    if face_obs.yaw is not None and abs(float(face_obs.yaw)) > float(flag_cfg["profile_yaw_deg"]):
        flags.append("profile view")

    if face_obs.pitch is not None and float(face_obs.pitch) < float(flag_cfg["looking_down_pitch_deg"]):
        flags.append("looking down")

    if other_person_boxes and getattr(face_obs, "person_box", None) is not None:
        from pipeline.faces import box_iou

        pbox = [float(v) for v in face_obs.person_box]
        if any(box_iou(pbox, other) > 0.2 for other in other_person_boxes):
            flags.append("overlapping person")

    return flags
