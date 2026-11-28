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

---

## Proposed additions, need team agreement

Generated from `pipeline/contract.py` (`PipelineResult`, `Frame`, `FLAG_VOCAB`, `RELIABILITY_VALUES`). All new fields are optional with defaults so `docs/sample_result.json` continues to validate unchanged.

### `PipelineResult` optional/updated fields
| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `person_track_id` | `Optional[int]` | `None` | Track ID of the linked person, or `null` if no person/face is found. |
| `link_confidence` | `Optional[str]` | `None` | Linking confidence (`"High"`, `"Medium"`, `"Low"`). |
| `link_reason` | `Optional[str]` | `None` | Explanation of track linking or why no track was chosen. |
| `link_low_margin` | `Optional[bool]` | `False` | `true` when the top two candidate tracks had a narrow score margin. |
| `selection_reason` | `Optional[str]` | `None` | Explanation when no frontal face or no face is visible. |
| `timings_ms` | `Optional[dict[str, float]]` | `None` | Stage-by-stage elapsed time in milliseconds. |
| `served_from_demo_pack` | `Optional[bool]` | `False` | `true` when served from `DEMO_PACK_DIR` (also on `IndexResult` and `SearchResult`). UIs must show a visible 'precomputed demo result' badge when this is true. |
| `requested_sample_fps` | `Optional[float]` | `None` | Requested frame-sampling rate before adaptive window fitting (also on `IndexResult`). |
| `effective_sample_fps` | `Optional[float]` | `None` | Actual frame-sampling rate used so the window fits `max_frames` (also on `IndexResult`). |
| `warnings` | `list[str]` | `[]` | Non-fatal warnings (e.g. lowered FPS for long window, truncated range, incomplete coverage; also on `IndexResult`). |
| `coverage_start_sec` | `Optional[float]` | `None` | Timestamp in seconds of the first sampled frame (also on `IndexResult`). |
| `coverage_end_sec` | `Optional[float]` | `None` | Timestamp in seconds of the last sampled frame (also on `IndexResult`). |

### `Frame` optional/updated fields
| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `frame_id` | `int \| str` | required | Supports `"f_<ms>"` string IDs alongside legacy integer IDs. |
| `match_ready` | `Optional[bool]` | `None` | Whether the face meets frontal/clarity thresholds for matching. |
| `rank_reason` | `Optional[str]` | `None` | Short summary of why the frame ranked in its position. |
| `crop_path` | `Optional[str]` | `None` | Path to the saved face crop `.jpg`. |
| `face_box` | `Optional[list[int]]` | `None` | `[x, y, w, h]` detected face box in full-frame pixels. |
| `flag_scores` | `Optional[dict[str, float]]` | `None` | Model-estimated probabilities `flag -> p` (e.g. `cap`, `mask`, `helmet`). |

### Constants (`pipeline/contract.py`)
- `RELIABILITY_VALUES`: `("High", "Medium", "Low")`
- `FLAG_VOCAB["current"]`: `("low light", "blur", "partial face", "small face", "profile view", "looking down", "overlapping person", "cap", "mask", "helmet")`
- `FLAG_VOCAB["planned"]`: `()`

### `IndexResult`, `IndexTrack`, `IndexFace` (`pipeline/index_clip.py`)
| Model | Field | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `IndexResult` | `clip_id`, `start_sec`, `end_sec` | `str`, `float`, `float` | required | Indexed clip ID and time range. |
| `IndexResult` | `tracks` | `list[IndexTrack]` | `[]` | Every tracked person in `[start_sec, end_sec]`. |
| `IndexResult` | `index_npz_path`, `index_json_path` | `str`, `str` | required | Saved `index.npz` (`N x 512` float32 embeddings + `metadata_json`) and `index.json`. |
| `IndexResult` | `total_embeddings`, `timings_ms` | `int`, `Optional[dict[str, float]]` | `0`, `None` | Total indexed embeddings and stage timings. |
| `IndexResult` | `requested_sample_fps`, `effective_sample_fps`, `warnings`, `coverage_start_sec`, `coverage_end_sec` | `Optional[float]`, `Optional[float]`, `list[str]`, `Optional[float]`, `Optional[float]` | `None`, `None`, `[]`, `None`, `None` | Requested/effective sampling FPS, truncation/coverage warnings, and sampled time coverage. |
| `IndexTrack` | `track_id`, `first_t`, `last_t` | `int`, `float`, `float` | required | Track ID and time span. |
| `IndexTrack` | `n_observations`, `short_track` | `int`, `bool` | `0`, `False` | Total track observations; `true` when `n_observations < 2`. |
| `IndexTrack` | `dwell_sec_in_zone` | `Optional[float]` | `None` | Zone dwell time (only populated when a zone is given). |
| `IndexTrack` | `faces`, `reason` | `list[IndexFace]`, `Optional[str]` | `[]`, `None` | Top `faces_per_track` faces, or reason when empty (`"No face found"`, `"Face under <N> px"`). |
| `IndexFace` | `t`, `quality_score`, `reliability`, `match_ready`, `flags`, `face_box`, `crop_path`, `frame_path`, `embedding_path` | `float`, `float`, `Literal`, `bool`, `list[str]`, `list[float]`, `str`, `str`, `str` | required | Indexed face metadata and saved artifact paths. |

### `SearchResult` & `SearchMatch` (`pipeline/compare.py`)
| Model | Field | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `SearchResult` | `basis` | `"original" \| "enhanced" \| "none"` | `"original"` | Which crop's embedding drove ranking (`enhanced` only when original fails). |
| `SearchResult` | `banner` | `str` | `"Possible leads only. A person must verify."` | Mandatory human-verification notice. |
| `SearchResult` | `reliability_note` | `Optional[str]` | `None` | Set to `"based on ENHANCED image, low reliability"` when `basis == "enhanced"`. |
| `SearchResult` | `top_level_warning`, `reason` | `Optional[str]`, `Optional[str]` | `None`, `None` | Set when any match warns of disagreement, or when no embedding could be extracted. |
| `SearchResult` | `matches` | `list[SearchMatch]` | `[]` | Ranked top-K leads. |
| `SearchMatch` | `track_id`, `t`, `similarity` | `int`, `float`, `float` | required | Matched track ID, timestamp, and primary cosine similarity. |
| `SearchMatch` | `similarity_secondary`, `delta`, `warning` | `Optional[float]`, `Optional[float]`, `Optional[str]` | `None` | Secondary (enhanced) similarity, `abs` difference, and warning if `delta > disagreement_warn`. |
| `SearchMatch` | `crop_path`, `reliability`, `match_ready` | `str`, `Optional[str]`, `Optional[bool]` | `""`, `None`, `None` | Matched crop path and quality metadata. |

### Backend Comparison Helpers (`pipeline/compare.py`, `pipeline/adapter.py`, `pipeline/fake_pipeline.py`)
- `ENHANCEMENT_WARNING`: `"Enhancement changed the result. Treat with caution."` (single source of truth).
- `determine_basis(original_embedding, enhanced_embedding) -> dict`: returns `{"basis", "reliability_note", "reason", "banner"}`. Original embedding present selects `"original"`; only enhanced present selects `"enhanced"` with `reliability_note = "based on ENHANCED image, low reliability"`; neither selects `"none"` with a non-empty `reason`.
- `secondary_scores(enhanced_crop_path, rows, original_scores, warn=None) -> dict` (also exposed via `adapter.get_secondary_scores()`): embeds `enhanced_crop_path` with padded retry against `(N, 512)` candidate `rows`, compares cosine similarities to `original_scores` using `disagreement_warn` from `pipeline/config/compare.json` (`0.15` by default), and returns:
  - `rows`: `list[{"similarity_secondary": float | None, "delta": float | None, "warning": str | None}]`
  - `basis`: `"original"`
  - `reliability_note`: `str | None`
  - `top_level_warning`: `ENHANCEMENT_WARNING` if any row triggered a warning, else `None`
  - `enhanced_embedding_found`: `bool` (`false` yields `similarity_secondary=None` for all rows and a descriptive `note`)
  - `note`: `str | None`

### Errors (`pipeline/errors.py`)
| Exception | `code` | When raised |
| --- | --- | --- |
| `PipelineError` | `PIPELINE_ERROR` | Base class for all pipeline errors. |
| `VideoNotFoundError` | `VIDEO_NOT_FOUND` | Input `clip_path` does not exist. |
| `VideoUnreadableError` | `VIDEO_UNREADABLE` | `ffprobe` / OpenCV cannot read the clip or find a video stream. |
| `InvalidArgumentError` | `INVALID_ARGUMENT` | `tx_offset_sec` outside `[0, duration]`, `window_sec <= 0`, `sample_fps <= 0`, invalid `tracker`, or invalid `zone_polygon_norm`. |
| `ZoneNotFoundError` | `ZONE_NOT_FOUND` | Unknown `atm_id` (when `zone_polygon_norm` is `None`). |
| `ModelLoadError` | `MODEL_LOAD_ERROR` | Required ML model fails to load. |

> Note: "No person in zone" and "no face found" are **not** errors; they return a valid `PipelineResult` with `best_frames=[]` and `person_track_id=None`.


