# Strix ML Pipeline

Strix extracts clear face evidence from ATM CCTV footage around a transaction timestamp, scores each candidate frame for frontalness, sharpness, size, illumination, and occluders, and indexes clips for human-verified face similarity search.

---

## Core Functions

- `pipeline.adapter.get_run() -> Callable` / `get_index_clip() -> Callable` / `get_search() -> Callable`
  Selects `fake_pipeline` (`USE_FAKE_PIPELINE=1`), `demo_pack` cache (`DEMO_PACK_DIR=demo_pack`), or the real ML pipeline.
- `pipeline.run_pipeline.run(clip_path, tx_offset_sec, window_sec=10, atm_id="", transaction_time=None, sample_fps=2.0, tracker="iou", out_dir="data/outputs", zone_polygon_norm=None, progress_cb=None) -> PipelineResult`
  Samples frames (VFR-safe), detects/tracks persons, links the ATM zone track, detects faces, scores quality + CLIP occluders, and saves top frames, crops, embeddings, and `result.json`.
- `pipeline.index_clip.index_clip(clip_path, start_sec=0.0, end_sec=None, sample_fps=1.0, tracker="iou", faces_per_track=3, min_face_px=40, out_dir="data/outputs", zone_polygon_norm=None, atm_id=None, progress_cb=None, max_seconds=600.0) -> IndexResult`
  Streams long clips in 100-frame chunks and writes `index.npz` + `index.json`.
- `pipeline.enhance.enhance_frame(frame_path, crop_box, method="lanczos", scale=4, out_dir=None) -> Enhancement`
  Crops first, Lanczos-upscales (`2x`/`4x`), prepends a red `ENHANCED x<scale>` banner strip above the crop, caches by SHA-256, and never modifies the original.
- `pipeline.compare.search_with_enhancement(index_dir, original_crop_path, enhanced_crop_path=None, exclude_track=None, top_k=None, original_embedding=None, enhanced_embedding=None) -> SearchResult`
  Ranks leads using the original embedding (`basis="original"`) with the enhanced embedding as a secondary check (warns if `delta > 0.15`).

---

## CLI Commands

```bash
# Run transaction evidence extraction
python -m pipeline.run_pipeline data/samples/sample2.mp4 --atm-id atm_155 --tx 155 --window 6

# Index a clip for search
python -m pipeline.index_clip data/samples/sample2.mp4 --start 0 --end 248

# Enhance a frame from result.json
python -m pipeline.enhance --result data/outputs/sample2/tx155_w6_atm_155/result.json --frame f_153013 --scale 4

# Search index with original + enhanced check
python scripts/search_enhanced.py --index data/outputs/sample2/index_s0_e247p887 --result data/outputs/sample2/tx155_w6_atm_155/result.json --frame f_153013

# Run evaluation harness / verify offline readiness
python scripts/run_eval.py --manifest data/samples/manifest.csv
python scripts/verify_offline.py
```

---

## Hardware & Measured Times

- **Hardware**: Ubuntu Linux, CPU inference for InsightFace/OpenCLIP (`CUDAExecutionProvider` falls back to CPU when CUDA 13 runtime libs are absent), Faster R-CNN MobileNetV3 on PyTorch `2.6.0+cu124`.
- **Measured times** (from [docs/eval_report.md](file:///home/mohit/Strix/docs/eval_report.md) on `data/samples/sample2.mp4`):
  - `atm_40` (`tx=40`, `window=10`): `32.06 s` (`link_ok=True`, `frontal_ok=True`)
  - `atm_155` (`tx=155`, `window=6`): `15.67 s` (`link_ok=True`, `frontal_ok=True`, 5 `match_ready` frames)
  - `empty_120` (`tx=120`, `window=8`): `4.38 s` (`link_ok=True`, no person linked)

---

## Honest Limits & Safety Rules

- **Limits**: Validated on a small practice clip (`sample2.mp4`, handheld/VFR footage); CLIP occluder thresholds (`cap`, `mask`, `helmet`) are starting values not yet tuned on a labeled occluder dataset; Lanczos enhancement is for human visual review and does not improve face-matching accuracy; InsightFace `buffalo_l` licence must be confirmed with organisers (see [docs/LICENCES.md](file:///home/mohit/Strix/docs/LICENCES.md)).
- **Safety**: Possible leads only — no automatic identification, human verification required; every enhanced crop is visibly stamped `ENHANCED x<scale>` and never overwrites the original; no real personal data or video files are committed to git (`data/` is git-ignored).
