# Strix backend: build spec

Owner: Anshika. Stack decided by the team plan: FastAPI, SQLite, JWT with roles, audit log, FAISS-style search, ReportLab PDF, Docker Compose.
Run everything from the REPO ROOT: `uvicorn backend.app.main:app --reload --port 8000` and `pytest backend/tests -q`.

---------------------------------------------------------------------
## 1. Facts about the existing pipeline (verified from the repo)

- Entry point: `from pipeline.adapter import get_run`; `run = get_run()`.
  With `USE_FAKE_PIPELINE=1` it returns `pipeline.fake_pipeline.run`, otherwise `pipeline.run_pipeline.run`.
- Real signature: `run(clip_path, tx_offset_sec, window_sec=10, atm_id="", transaction_time=None, sample_fps=2.0, tracker="iou", out_dir="data/outputs") -> PipelineResult`.
  The fake accepts at least `(clip_path, tx_offset_sec, window_sec)`.
- `run()` BLOCKS for 15-30 s (CPU/GPU heavy). Never call it in an async handler. Use ONE worker thread (`max_workers=1`), one job at a time (the demo GPU has 4 GB).
- Models: `from pipeline.contract import PipelineResult, Frame, Enhancement, Metrics`. Importing this is safe on a Mac (pydantic only). `pipeline/__init__.py` is empty.
- `Frame.frame_id` is `int | str` (for example `142` or `"f_1234"`). Store it as TEXT. Key frames by `(run_id, frame_id)`.
- Optional result fields (may be None): `match_ready`, `rank_reason`, `crop_path` per frame; `link_confidence`, `link_reason`, `selection_reason`, `timings_ms` per result; `person_track_id` can be None.
- "No person in zone" and "no face" are NOT errors. They return `best_frames=[]` with the reason in `link_reason` / `selection_reason`. Show `selection_reason` when `best_frames` is empty or all frames are Low.
- Flags are an OPEN list of strings (today: "low light", "blur", "partial face", "small face", "profile view", "looking down"; later "cap", "mask", "helmet"). Never validate against a fixed list.
- Reliability is "High" / "Medium" / "Low".
- Embeddings: `.npy`, 512-d float32, L2-normalised. Similarity = cosine = inner product.
- Paths in results are relative to the current working directory (for example `data/outputs/...`) and in fake mode the files DO NOT EXIST. Both must be handled (sections 5.2 and 6).
- NOT BUILT YET (must be optional, must not break when absent): `progress_cb` argument, `zone_polygon_norm` argument, `PipelineError` with `.code` (VideoNotFound, VideoUnreadable, InvalidArgument, ZoneNotFound, ModelLoad), `pipeline.index_clip`, `pipeline.enhance.enhance_frame`. Detect with `inspect.signature` / try-import / `getattr`. Never assume.
- `pipeline.fake_pipeline.fake_enhance(image_path, crop_box, scale) -> Path` exists today (Pillow, Lanczos, ENHANCED burned into pixels, original untouched, saves `<n>_enh_x<scale>.jpg` next to the original).
- The 200-frame cap inside the pipeline: at `sample_fps` the window `[tx - w, tx + w]` must satisfy `2 * w * sample_fps <= 200`. Reject larger requests with a clear 422.

---------------------------------------------------------------------
## 2. Dependencies (put in backend/requirements.txt, pin the versions you actually tested)

fastapi, uvicorn, sqlalchemy (2.x), pydantic-settings, PyJWT, bcrypt (use the `bcrypt` package DIRECTLY; do not use passlib, it breaks with newer bcrypt), python-multipart, reportlab, pillow, numpy, pytest, httpx.
Optional: `faiss-cpu`. Try to import it; if it is missing or fails, fall back to a numpy search with the same interface. Both must pass the same tests.
System: `ffmpeg` and `ffprobe` on PATH (check at startup and report clearly if missing).

---------------------------------------------------------------------
## 3. Layout

```
backend/
  __init__.py  AGENTS.md  SPEC.md  README.md  API.md  PROPOSALS.md  requirements.txt  Dockerfile
  app/
    __init__.py  main.py  config.py  db.py  models.py  schemas.py  errors.py
    security.py  deps.py  audit.py  signing.py
    routes/  auth.py users.py clips.py runs.py files.py search.py evidence.py audit.py frames.py
    services/  storage.py probe.py pipeline_gateway.py jobs.py search_index.py evidence_pdf.py fake_assets.py enhance.py
  scripts/  seed_users.py  seed_fake_assets.py  smoke_test.py
  tests/  conftest.py  test_*.py
docker-compose.yml (repo root, CPU baseline, backend service only)
```
`backend/tests/conftest.py` inserts the repo root on `sys.path` so `import pipeline` works.

---------------------------------------------------------------------
## 4. Configuration (read from the repo-root `.env` via pydantic-settings; document new keys in backend/README.md, do NOT edit .env.example)

| Key | Default | Notes |
|---|---|---|
| USE_FAKE_PIPELINE | 1 | "1" fake, "0" real |
| DATA_DIR | ./data | uploads, outputs, db live here (never in Git) |
| JWT_SECRET | none | REQUIRED, refuse to start if missing or shorter than 32 chars. README shows how to generate one |
| JWT_EXPIRE_MIN | 480 | |
| CORS_ORIGINS | http://localhost:5173,http://localhost:3000 | comma list; never "*" |
| MAX_UPLOAD_MB | 500 | |
| SIGNED_URL_TTL_SEC | 900 | |
| DISPLAY_TZ | Asia/Kolkata | bank logs are local time |
| EMBED_DIM | 512 | |
| MODEL_LABELS | see 7.6 | strings printed on the evidence sheet |

Error format for every error: `{"detail": "<human message>", "code": "<UPPER_SNAKE>"}`.
Public config endpoint `GET /config/public` returns: `pipeline_mode` ("fake"/"real"), notice text, limits, accepted extensions, model labels. The UI shows a visible "FAKE PIPELINE, DEMO DATA" banner when fake. The evidence PDF prints the same warning in fake mode, so fake data can never be mistaken for real.
Notice text (constant): "Possible matches only. A human investigator must verify every result."

---------------------------------------------------------------------
## 5. Data model (SQLAlchemy 2.0, SQLite at DATA_DIR/strix.db, `PRAGMA foreign_keys=ON`, WAL)

### 5.1 Tables
- `users`: id, username (unique), password_hash, role ("admin" | "investigator"), full_name, active, created_at.
- `clips`: id (uuid), original_filename, stored_path (RELATIVE to DATA_DIR), sha256, size_bytes, duration_sec, fps, width, height, codec, container, clip_start_time (naive local datetime, nullable), clip_start_source ("ffprobe_converted" | "user" | "unknown"), atm_id (nullable), zone_polygon_norm (JSON list of [x,y] in 0-1, at least 3 points, nullable), notes, uploaded_by, created_at.
- `runs`: id (int), clip_id, status ("queued" | "running" | "done" | "failed"), stage, progress (0-1 or null), error_code, error_message, transaction_time (naive local), tx_offset_sec, window_sec, sample_fps, tracker, atm_id, pipeline_mode, result_json (full PipelineResult JSON, paths already normalised), created_by, created_at, started_at, finished_at.
- `frames`: id, run_id, frame_id (TEXT), timestamp_sec, quality_score, reliability, flags (JSON), match_ready, rank_reason, frame_path_rel, crop_path_rel, embedding_path_rel, enhanced (bool), enhancement (JSON), metrics (JSON), selected (bool, default false). Unique (run_id, frame_id).
- `searches`: id, run_id, frame_pk, top_k, results (JSON), created_by, created_at.
- `audit_log` (append-only): id, ts_utc, user_id, username, role, action, target_type, target_id, details (JSON), ip, prev_hash, entry_hash.
  `entry_hash = sha256(prev_hash + canonical_json(row without entry_hash))` so tampering is detectable. Add SQLite triggers that RAISE on UPDATE or DELETE of `audit_log`. No route edits or deletes it.

### 5.2 Path rule (critical)
All paths stored in the DB are RELATIVE to DATA_DIR and use forward slashes. `services/storage.py` provides `to_rel(path)`:
tries the path as given (absolute), then relative to the current working directory, then relative to DATA_DIR, then with a leading `data/` stripped; the first candidate that exists-or-lies inside DATA_DIR wins. If it lies outside DATA_DIR, raise (do not store it). `from_rel(rel)` joins to DATA_DIR and rejects `..`, absolute paths and anything that resolves (after symlinks) outside DATA_DIR.

---------------------------------------------------------------------
## 6. API (all JSON; all routes need a Bearer token except /health, /config/public, /auth/login, /files)

Browsers cannot send an Authorization header from `<img>` or `<video>` tags. So images and video are served with SIGNED URLs: `signing.py` makes `/files?p=<rel_path>&uid=<user_id>&exp=<unix>&sig=<hmac>`; HMAC-SHA256 with JWT_SECRET over `p|uid|exp`, constant-time compare, expires after SIGNED_URL_TTL_SEC, only paths inside DATA_DIR/uploads or DATA_DIR/outputs. Result and clip JSON include ready-made signed URLs (`image_url`, `crop_url`, `enhanced_url`, `video_url`). Add `?download=1` support: sets Content-Disposition and writes a `download_frame` / `download_video` audit entry.
Video must support HTTP Range requests (seeking). Verify with `curl -r 0-99`; if FileResponse does not do it, write a small range handler.

Auth: `POST /auth/login` (JSON `{username, password}` -> `{access_token, token_type, user}`), `GET /auth/me`.
Users (admin): `POST /users`, `GET /users`. Roles: admin can do everything plus audit and users; investigator can upload, process, search, enhance, export evidence.
Clips: `POST /clips` (multipart: file, optional atm_id, clip_start_time, notes), `GET /clips`, `GET /clips/{id}`, `PATCH /clips/{id}` (clip_start_time, atm_id, zone_polygon_norm, notes), `GET /clips/{id}/video`.
Processing: `POST /clips/{id}/process` (body: transaction_time, window_sec=10, sample_fps=2.0, tracker="iou", atm_id optional) -> 202 `{run_id, status}`; `GET /runs/{run_id}` (status, stage, progress, error, and result when done); `GET /clips/{id}/runs`; `GET /runs/{run_id}/result`.
Frames: `POST /runs/{run_id}/selection` (body: `{frame_ids: [...]}`; replaces the selected set), `POST /runs/{run_id}/frames/{frame_id}/enhance` (phase 7).
Search: `POST /search` (body: `{run_id, frame_id, top_k=10}`), `GET /searches/{id}`.
Evidence: `GET /runs/{run_id}/evidence.pdf?search_id=` .
Audit (admin): `GET /audit?limit&offset&action&username`, `GET /audit/export.csv`, `GET /audit/verify` (re-computes the hash chain, returns ok or the first bad id).
Misc: `GET /health`, `GET /config/public`.

Audit actions to record: login_success, login_failed, upload, process_started, process_finished, process_failed, search, download_evidence, download_video, download_frame, frames_selected, frame_enhanced, frames_extracted, user_created, audit_export. Never log passwords or tokens. Add a small in-memory throttle: after 5 failed logins in 5 minutes for a username+IP, return 429.

---------------------------------------------------------------------
## 7. Services

### 7.1 probe.py
Own ffprobe call (`ffprobe -v quiet -print_format json -show_format -show_streams`) via subprocess with a timeout. Returns duration, fps (parse "30000/1001"), width, height, codec, container, rotation, and `creation_time` from format or stream tags if present. Raise a clear `UNREADABLE_VIDEO` error if there is no video stream or ffprobe fails; `FFPROBE_MISSING` if the binary is absent.

### 7.2 Upload
Accepted extensions (case-insensitive): mp4, avi, mov, mkv, wmv, flv, mpeg, mpg. Stream the upload to a temp file in chunks while computing SHA-256, enforce MAX_UPLOAD_MB, then probe. If probing fails, delete the file and return 422 with export/conversion advice ("Export the clip as MP4 (H.264) from the DVR/NVR software, or convert it with FFmpeg"). Store at `uploads/<clip_id>/<safe_name>`; sanitise the filename (strip path parts, limit characters). If `pipeline.ingest` exists later it is Aditi's module: leave a marked hook in `services/probe.py`, do not guess its API.
Clip start time: if ffprobe gave `creation_time` (usually UTC), convert to DISPLAY_TZ and store with source "ffprobe_converted"; the investigator can override it with PATCH (source "user"). If nothing is available, store null with source "unknown" and require it (or an explicit tx offset) before processing.

### 7.3 Transaction time
`tx_offset_sec = transaction_time - clip_start_time` (both naive local). Validate `0 <= tx_offset_sec <= duration_sec`; otherwise 422 `TX_OUT_OF_RANGE` with both times and the duration in the message so a UTC/IST mix-up is obvious. Also enforce `2 * window_sec * sample_fps <= 200`. Allowed ranges: window_sec 1-100, sample_fps 0.5-5, tracker "iou" or "bytetrack".

### 7.4 pipeline_gateway.py
- Lazy `from pipeline.adapter import get_run` inside the function.
- Build kwargs, then keep only those the target accepts (`inspect.signature`). Always pass `clip_path`, `tx_offset_sec`, `window_sec`; pass `atm_id`, `transaction_time`, `sample_fps`, `tracker`, absolute `out_dir=DATA_DIR/outputs`, `zone_polygon_norm`, `progress_cb` ONLY if accepted.
- After the call: normalise every path with `to_rel`, create `frames` rows, store `result_json`.
- Errors: `getattr(exc, "code", None)` becomes `error_code`, otherwise "PIPELINE_FAILED". Store a human message. Never leak stack traces to the client. Log the traceback server-side.
- Fake mode: write per-run placeholder assets (section 7.5) so paths exist and search works.

### 7.5 fake_assets.py and scripts/seed_fake_assets.py
In fake mode, after the fake `run()` returns, materialise files for THIS run under `outputs/<clip_id>/run_<run_id>/`: a 640x480 placeholder JPG per frame (text "FAKE FRAME <id>"), a crop JPG, and a 512-d `.npy` embedding = L2-normalise(person_vector + 0.15 * noise). `person_vector` is seeded from a person key: the filename stem before the first underscore (so `A_clip1.mp4` and `A_clip2.mp4` look like the same person, `B_clip1.mp4` a different one). Rewrite the result paths to these files. The script lets me pre-create the same assets for manual testing.

### 7.6 jobs.py
`ThreadPoolExecutor(max_workers=1)`. On startup mark any `queued`/`running` run as `failed` with `SERVER_RESTARTED`. Status goes queued -> running -> done/failed, with `stage` and `progress` updated if the pipeline reports them (otherwise stage "processing", progress null). Each worker uses its own DB session. Audit `process_started`, `process_finished`, `process_failed`.
Model labels for the evidence sheet (config strings): "Person detector: torchvision Faster R-CNN MobileNetV3-Large 320 FPN (COCO)", "Tracker: IoU / ByteTrack", "Faces: InsightFace buffalo_l (SCRFD + ArcFace)". In fake mode print "FAKE PIPELINE".

### 7.7 search_index.py
Interface: `add(items)`, `remove_run(run_id)`, `search(vec, top_k, exclude_clip_id) -> list`, `count()`. In-memory matrix + id list, rebuilt from the DB at startup and updated when a run finishes. Use faiss `IndexFlatIP` if it imports, else numpy `matrix @ vec`. Skip vectors with the wrong dimension or NaN (log a warning). Re-normalise on load. Results only include OTHER clips than the query's clip, sorted by score, each with: clip_id, filename, run_id, frame_id, timestamp_sec, score, reliability, flags, crop_url, frame_url, plus `notice` and `score_note: "uncalibrated similarity, tune on sample data"`. Do not invent decision thresholds. `scope: "frames from processed runs only"` (until `index_clip` exists; leave a clearly marked TODO and a `POST /clips/{id}/index` that returns 501 NOT_AVAILABLE until `pipeline.index_clip` can be imported).

### 7.8 evidence_pdf.py (ReportLab Platypus)
Title "Evidence Sheet", evidence ID `EV-<run_id>`, generated-at time, investigator full name, clip filename, clip SHA-256, transaction time, clip start time and source, offset, window, link confidence and reason, selection reason, model labels, pipeline mode warning if fake. Then a table of frames (use `selected` frames if any are selected, else all `best_frames`): image (crop if present else frame), timestamp, quality score, reliability, flags, match_ready, rank_reason. If a frame has an enhancement: original and enhanced side by side, the enhanced one captioned "ENHANCED (method, scale, model version)". If `search_id` is given: a results section with similarity scores and the score note. Footer on every page: the notice and page numbers. Handle missing image files (print "image unavailable"), long text, and non-ASCII names without crashing. Log `download_evidence` with the PDF's SHA-256 in `details`.

### 7.9 enhance.py (phase 7)
Request: `{crop_box: [x,y,w,h], scale: 2|4, method: "lanczos"}`. Validate the crop lies inside the image and has w,h >= 8. Cache by hash of (frame, crop, method, scale). Use `pipeline.enhance.enhance_frame` if importable and the method is supported, else `pipeline.fake_pipeline.fake_enhance` (Lanczos) and build an `Enhancement` object (`method="lanczos"`, `model_version="lanczos_v1"`, `search_embedding_source="original"`). Confirm the original file's SHA-256 is unchanged and the ENHANCED label is burned into the pixels. Store in `frames.enhancement`, set `enhanced=true`, audit `frame_enhanced`.

---------------------------------------------------------------------
## 8. Phases (do one at a time; each has acceptance tests)

1. **Skeleton**: config, db, errors, /health, /config/public, CORS, JWT_SECRET check. Tests: health ok; missing secret refuses to start; error format.
2. **Auth, users, audit**: login, me, roles, throttle, audit with hash chain and triggers, audit list/CSV/verify, `scripts/seed_users.py` (passwords from env or random and printed once). Tests: wrong password 401 and logged; investigator gets 403 on /audit; verify detects a tampered row; UPDATE/DELETE on audit_log fails.
3. **Storage, probe, upload, clips, signed files**: Tests (make a 5 s clip with `ffmpeg -f lavfi -i testsrc=duration=5:size=320x240:rate=10`; skip if ffmpeg is absent): bad extension 422; text file renamed .mp4 422; oversize 413; SHA-256 correct; creation_time conversion; signed URL works, expired URL 403, tampered signature 403, `../` and absolute paths 403/404; Range request returns 206.
4. **Gateway, jobs, runs, results, fake assets**: Tests: process returns 202, status goes queued -> done; offset out of range 422; window cap 422; frame_id int and string both stored; result paths normalised and files exist; failed pipeline stores error_code; restart marks running as failed; two jobs run one after another.
5. **Search**: Tests: same person key matches with a high score, different person lower; query clip excluded; wrong-dim vectors skipped; numpy and faiss (if installed) agree; response has the notice.
6. **Selection and evidence PDF**: Tests: PDF starts with `%PDF`; works with zero frames and with a missing image; fake mode prints the warning; audit entry has the PDF hash.
7. **Enhancement**: Tests as in 7.9.
8. **Docker and docs**: `backend/Dockerfile` (python:3.11-slim, apt ffmpeg, backend/requirements.txt, copies backend/ and pipeline/, USE_FAKE_PIPELINE=1, healthcheck), `docker-compose.yml` at the root (backend service, ./data volume, env from .env), `backend/README.md` (Mac setup, env keys, how to run, how to test), `backend/API.md` (every route with a request and response example), and `scripts/smoke_test.py` (login -> upload -> process -> poll -> search -> evidence PDF against a running server).
9. **Optional, only after 1-8 pass**: `POST /clips/{id}/frames/extract` (ffmpeg `-ss` before `-i`, max 200 frames, timestamp = start + index/fps, saved in the response); wire `progress_cb`, `zone_polygon_norm`, `PipelineError` codes and `index_clip` once those exist in `pipeline/`.

Definition of done for every phase: `pytest backend/tests -q` passes (show the output), `python scripts/check_no_ultralytics.py` passes, the server was started and the new endpoints called with curl (show the output), `git status` shows no data, .env or secrets, and `backend/API.md` is updated.

---------------------------------------------------------------------
## 9. Out of scope
Matching against real criminal or Aadhaar databases, automatic identification, live connection to bank CCTV, any change outside backend/, docker-compose.yml.
