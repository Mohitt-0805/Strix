# Strix Pipeline API Contract

This document defines the shared JSON output contract (`docs/sample_result.json`, validated by `pipeline/contract.py`) and the lightweight `pipeline/fake_pipeline.py` interface for backend and frontend integration.

---

## JSON Output Schema (`PipelineResult`)

Top-level object:

| Field | Type | Description |
| --- | --- | --- |
| `clip_id` | `string` | Identifier derived from the input clip filename. |
| `transaction_time` | `string` | ISO-8601 transaction timestamp (e.g. `"2026-11-22T14:32:10"`). |
| `person_track_id` | `integer` | Track ID of the person associated with the transaction window. |
| `best_frames` | `list[Frame]` | Ranked candidate evidence frames (possible matches only; no automatic ID). |

### `Frame`

| Field | Type | Description |
| --- | --- | --- |
| `frame_id` | `integer` | Zero-based or clip frame index. |
| `frame_path` | `string` | Path to the saved original frame/crop. |
| `timestamp_sec` | `float` | Timestamp of the frame within the clip (seconds). |
| `quality_score` | `float` | Normalized quality score in `[0.0, 1.0]`. |
| `reliability` | `"High" \| "Medium" \| "Low"` | Qualitative reliability tier. |
| `flags` | `list[string]` | Quality/warning flags (e.g. `["low_resolution"]`). |
| `enhanced` | `bool` | Whether a separate enhanced crop was generated. |
| `enhancement` | `Enhancement \| null` | `null` when `enhanced` is `false`; otherwise enhancement metadata. |
| `metrics` | `Metrics` | Per-frame face quality metrics. |
| `embedding_path` | `string` | Path to the saved face embedding `.npy` file. |

### `Metrics`

| Field | Type | Description |
| --- | --- | --- |
| `sharpness` | `float` | Sharpness score. |
| `face_size` | `float` | Face bounding-box size in pixels. |
| `pose_yaw` | `float` | Estimated yaw angle in degrees. |
| `illumination` | `float` | Illumination score. |
| `occlusion` | `float` | Estimated occlusion score. |

### `Enhancement`

| Field | Type | Description |
| --- | --- | --- |
| `enhanced_path` | `string` | Path to the enhanced image (`ENHANCED` stamped in pixels; original untouched). |
| `method` | `string` | Super-resolution/enhancement method (e.g. `"espcn"`). |
| `scale` | `integer` | Upscale factor (e.g. `4`). |
| `model_version` | `string` | Model identifier (e.g. `"espcn_x4_v1"`). |
| `crop_box` | `list[int]` | `[x, y, w, h]` crop region in the source frame. |
| `search_embedding_source` | `string` | Embedding source used for search (e.g. `"original"`). |

---

## Python Functions (`pipeline/fake_pipeline.py`)

```python
def run(
    clip_path: str | Path,
    tx_offset_sec: float,
    window_sec: float = 10,
) -> PipelineResult:
    ...
```

Returns a validated `PipelineResult` built from `docs/sample_result.json` with `clip_id` set to `Path(clip_path).stem`.

```python
def fake_enhance(
    image_path: str | Path,
    crop_box: list[int] | tuple[int, int, int, int],
    scale: int,
) -> Path:
    ...
```

Crops `[x, y, w, h]` and resizes by `scale` using Pillow Lanczos, burns `ENHANCED` into the pixels with `ImageDraw`, saves next to the original as `<name>_enh_x<scale>.jpg`, and leaves the original file unmodified.
