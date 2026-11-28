# Strix Backend API

Base URL (local): `http://127.0.0.1:8000`

> **Development DB note:** In development, no SQLite schema migrations are maintained. Whenever the schema changes (including Phase 6A, Phase 6B, and Phase 9), delete `data/strix.db` (and any `data/strix.db-wal` / `data/strix.db-shm`) and re-run `backend/scripts/seed_users.py`.

## Error Format

Every error response uses the uniform JSON shape:

```json
{
  "detail": "Not Found",
  "code": "NOT_FOUND"
}
```

---

## Frontend Integration Notes

- **Signed media URLs (`video_url`, `image_url`, `crop_url`, `enhanced_url`, `original_url`, `frame_url`):**
  Every media URL returned by the API is a **relative** path (`/files?p=...&uid=...&exp=...&sig=...`). Prefix it with the API base URL (e.g., `${API_BASE_URL}${frame.image_url}`) and pass it directly to `<img>` or `<video>` tags **without** any `Authorization` header (browsers do not send Bearer headers from media tags, and `/files` authenticates via the short-lived HMAC signature). Video supports HTTP `Range` seeking automatically. Missing image files return `null` URLs in search and index responses rather than breaking.
- **`pipeline_mode` and `demo_pack_enabled` from `/config/public`:**
  Fetch `GET /config/public` on app load. When `pipeline_mode === "fake"`, display a prominent banner using `banner` (`"FAKE PIPELINE, DEMO DATA"`) so demo results are never mistaken for real pipeline output. Always display `notice` (`"Possible matches only. A human investigator must verify every result."`) alongside results. When `DEMO_PACK_DIR` is set (`demo_pack_enabled: true`) and `USE_FAKE_PIPELINE=0`, matching runs (`clip_name`, `atm_id`, `tx_offset_sec` to 3 decimals, `window_sec`) and indexes (`clip_name`) are served from pre-computed cache and labelled `served_from_demo_pack: true` on `GET /runs/{id}`, `GET /runs/{id}/result`, `GET /clips/{id}/indexes`, `GET /indexes/{id}`, and on the exported Evidence PDF.
- **Polling runs and index jobs:**
  - `POST /clips/{id}/process` returns `202` `{run_id, status}`. Poll `GET /runs/{run_id}` (e.g., every 500–1000 ms) until `status` is `"done"` or `"failed"`. Read `stage`, `progress` (`0.0–1.0` or `null`), and `progress_message` for live progress UI.
  - `POST /clips/{id}/index` (and automatic upload indexing when `AUTO_INDEX_ON_UPLOAD=1`) returns `202` `{index_id, status}`. Poll `GET /indexes/{index_id}` using the same `status`, `stage`, `progress`, and `progress_message` fields. Note that processing runs have queue priority `0` and preempt waiting index jobs (`1`).
- **Typed failure fields (`error_code`, `error_message`, `error_advice`):**
  When a run or index job has `status === "failed"`, display `error_advice` (human remediation guidance) alongside `error_message` and `error_code` (`VIDEO_NOT_FOUND`, `VIDEO_UNREADABLE`, `INVALID_ARGUMENT`, `ZONE_NOT_FOUND`, `MODEL_LOAD` / `MODEL_LOAD_ERROR`).
- **Flags & `flag_scores`:**
  `flags` is an **open list of strings** (for example `"low light"`, `"blur"`, `"cap"`, `"mask"`, `"helmet"`)—never restrict UI rendering to a fixed enum. When `flag_scores` is present, render each scored flag as a model estimate (e.g., `cap (model estimate 0.71)`) and remind investigators that flags are model estimates that can be wrong in both directions.
- **`short_track` faces in search & index results:**
  `GET /indexes/{index_id}` marks `short_track: true` tracks with `confidence_note: "low confidence (short track)"`. `POST /search` hides `short_track` faces by default (`include_short_tracks: false`); surface an optional toggle to include them with a low-confidence badge.
- **`crop_box` coordinates:**
  `POST /runs/{run_id}/frames/{frame_id}/enhance` expects `crop_box: [x, y, w, h]` in **full-frame pixels** (`w, h >= 8` after clipping to image bounds) and `scale` of `2` or `4`. `face_box` on frames is `[x1, y1, x2, y2]` in full-frame pixels.
- **Downloading the Evidence PDF:**
  `GET /runs/{run_id}/evidence.pdf?search_id=` requires the `Authorization: Bearer <token>` header. Fetch it with `fetch(..., { headers: { Authorization: ... } })` as a `Blob` (`response.blob()`) and trigger download or open via `URL.createObjectURL(blob)`—do not navigate a plain `<a>` link without auth headers.

---

## Public Endpoints

### `GET /health`

Public health check verifying SQLite connectivity and `ffmpeg`/`ffprobe` availability.

**Request:**
```bash
curl -s http://127.0.0.1:8000/health
```

**Response (`200 OK`):**
```json
{
  "status": "ok",
  "db": "ok",
  "pipeline_mode": "fake",
  "ffmpeg": true,
  "ffprobe": true
}
```

---

### `GET /config/public`

Public non-secret configuration, limits, accepted video extensions, model labels, and the mandatory human-verification notice.

**Request:**
```bash
curl -s http://127.0.0.1:8000/config/public
```

**Response (`200 OK`):**
```json
{
  "pipeline_mode": "fake",
  "demo_pack_enabled": false,
  "banner": "FAKE PIPELINE, DEMO DATA",
  "notice": "Possible matches only. A human investigator must verify every result.",
  "limits": {
    "max_upload_mb": 500,
    "window_sec_min": 1,
    "window_sec_max": 100,
    "sample_fps_min": 0.5,
    "sample_fps_max": 5.0,
    "max_sampled_frames": 200,
    "embed_dim": 512,
    "signed_url_ttl_sec": 900
  },
  "accepted_extensions": ["mp4", "avi", "mov", "mkv", "wmv", "flv", "mpeg", "mpg"],
  "model_labels": ["FAKE PIPELINE"],
  "display_tz": "Asia/Kolkata"
}
```

---

## Auth Endpoints

### `POST /auth/login`

Authenticate with username and password (throttled after 5 failed attempts in 5 minutes per `username + IP` -> `429`).

**Request:**
```bash
curl -s -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"..."}'
```

**Response (`200 OK`):**
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "admin",
    "role": "admin",
    "full_name": "System Admin",
    "active": true,
    "created_at": "2026-11-26T12:55:00.000000"
  }
}
```

---

### `GET /auth/me`

Return the authenticated user's profile (`Bearer` token required).

**Request:**
```bash
curl -s http://127.0.0.1:8000/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

**Response (`200 OK`):**
```json
{
  "id": 1,
  "username": "admin",
  "role": "admin",
  "full_name": "System Admin",
  "active": true,
  "created_at": "2026-11-26T12:55:00.000000"
}
```

---

## User Management Endpoints (Admin Only)

### `POST /users`

Create an `admin` or `investigator` user (`409 USERNAME_EXISTS` on duplicate).

**Request:**
```bash
curl -s -X POST http://127.0.0.1:8000/users \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username":"analyst1","password":"StrongPassword99","role":"investigator","full_name":"Analyst One"}'
```

**Response (`201 Created`):**
```json
{
  "id": 3,
  "username": "analyst1",
  "role": "investigator",
  "full_name": "Analyst One",
  "active": true,
  "created_at": "2026-11-26T12:56:00.000000"
}
```

---

### `GET /users`

List all users ordered by `id`.

**Request:**
```bash
curl -s http://127.0.0.1:8000/users \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Response (`200 OK`):**
```json
[
  {
    "id": 1,
    "username": "admin",
    "role": "admin",
    "full_name": "System Admin",
    "active": true,
    "created_at": "2026-11-26T12:55:00.000000"
  }
]
```

---

## Audit Endpoints (Admin Only)

### `GET /audit`

List append-only hash-chained audit entries (`limit`, `offset`, `action`, `username`).

**Request:**
```bash
curl -s "http://127.0.0.1:8000/audit?limit=10&offset=0" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Response (`200 OK`):**
```json
{
  "items": [
    {
      "id": 1,
      "ts_utc": "2026-11-26T12:55:00.123456Z",
      "user_id": 1,
      "username": "admin",
      "role": "admin",
      "action": "login_success",
      "target_type": "user",
      "target_id": "1",
      "details": {},
      "ip": "127.0.0.1",
      "prev_hash": "0000000000000000000000000000000000000000000000000000000000000000",
      "entry_hash": "<sha256>"
    }
  ],
  "total": 1,
  "limit": 10,
  "offset": 0
}
```

---

### `GET /audit/export.csv`

Export the audit log as CSV and record an `audit_export` entry.

**Request:**
```bash
curl -s http://127.0.0.1:8000/audit/export.csv \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Response (`200 OK`, `text/csv`):**
```csv
id,ts_utc,user_id,username,role,action,target_type,target_id,details,ip,prev_hash,entry_hash
1,2026-11-26T12:55:00.123456Z,1,admin,admin,login_success,user,1,{},127.0.0.1,0000...,<sha256>
```

---

### `GET /audit/verify`

Recompute the SHA-256 hash chain across `audit_log` and report `ok` or the first corrupted `id`.

**Request:**
```bash
curl -s http://127.0.0.1:8000/audit/verify \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Response (`200 OK`):**
```json
{
  "ok": true,
  "checked_count": 2,
  "first_bad_id": null,
  "reason": null
}
```

---

## Clips, Zones & Signed Files Endpoints

### `POST /clips`

Stream-upload a video clip (`mp4, avi, mov, mkv, wmv, flv, mpeg, mpg`), compute SHA-256, probe metadata with `ffprobe`, convert `creation_time` to `DISPLAY_TZ`, and auto-queue an index job when `AUTO_INDEX_ON_UPLOAD=1`.

**Request (`multipart/form-data`):**
```bash
curl -s -X POST http://127.0.0.1:8000/clips \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@sample.mp4" \
  -F "atm_id=atm_demo" \
  -F "notes=Test upload"
```

**Response (`201 Created`):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "original_filename": "sample.mp4",
  "stored_path": "uploads/550e8400-e29b-41d4-a716-446655440000/sample.mp4",
  "sha256": "<sha256>",
  "size_bytes": 123456,
  "duration_sec": 5.0,
  "fps": 10.0,
  "width": 320,
  "height": 240,
  "codec": "h264",
  "container": "mov,mp4,m4a,3gp,3g2,mj2",
  "rotation": 0,
  "clip_start_time": "2026-11-26T15:30:00",
  "clip_start_source": "ffprobe_converted",
  "atm_id": "atm_demo",
  "zone_polygon_norm": null,
  "notes": "Test upload",
  "uploaded_by": 1,
  "created_at": "2026-11-26T13:05:00.000000",
  "video_url": "/files?p=uploads%2F...&uid=1&exp=...&sig=..."
}
```

---

### `GET /clips`

List uploaded clips newest-first (`Bearer` token required).

**Request:**
```bash
curl -s http://127.0.0.1:8000/clips -H "Authorization: Bearer $TOKEN"
```

**Response (`200 OK`):**
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "original_filename": "sample.mp4",
    "stored_path": "uploads/550e8400-e29b-41d4-a716-446655440000/sample.mp4",
    "sha256": "<sha256>",
    "size_bytes": 123456,
    "duration_sec": 5.0,
    "fps": 10.0,
    "width": 320,
    "height": 240,
    "codec": "h264",
    "container": "mov,mp4,m4a,3gp,3g2,mj2",
    "rotation": 0,
    "clip_start_time": "2026-11-26T15:30:00",
    "clip_start_source": "ffprobe_converted",
    "atm_id": "atm_demo",
    "zone_polygon_norm": null,
    "notes": "Test upload",
    "uploaded_by": 1,
    "created_at": "2026-11-26T13:05:00.000000",
    "video_url": "/files?p=uploads%2F...&uid=1&exp=...&sig=..."
  }
]
```

---

### `GET /clips/{id}`

Fetch a single clip by UUID (`Bearer` token required).

**Request:**
```bash
curl -s http://127.0.0.1:8000/clips/$CLIP_ID -H "Authorization: Bearer $TOKEN"
```

**Response (`200 OK`):** Same JSON object shape as `POST /clips`.

---

### `PATCH /clips/{id}`

Update `clip_start_time` (sets `clip_start_source="user"`), `atm_id`, `zone_polygon_norm` (at least 3 `[x, y]` points in `0..1`; invalid polygons return `422 ZONE_INVALID`), or `notes`.

**Request:**
```bash
curl -s -X PATCH http://127.0.0.1:8000/clips/$CLIP_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"zone_polygon_norm":[[0.1,0.1],[0.9,0.1],[0.9,0.9],[0.1,0.9]],"notes":"Lobby zone"}'
```

**Response (`200 OK`):** Returns the updated `ClipOut` JSON object.

---

### `GET /zones`

List configured ATM zones from `pipeline/config/atm_zone.json` sorted by `id` (`Bearer` token required).

**Request:**
```bash
curl -s http://127.0.0.1:8000/zones -H "Authorization: Bearer $TOKEN"
```

**Response (`200 OK`):**
```json
[
  {
    "id": "atm_01",
    "note": "Default normalized ATM standing zone (right-lower area)",
    "polygon": [[0.45, 0.35], [0.95, 0.35], [0.95, 0.95], [0.45, 0.95]]
  }
]
```

---

### `GET /clips/{id}/video`

Stream the uploaded clip video with HTTP `Range` (`206 Partial Content`) support. Add `?download=1` for `Content-Disposition: attachment` and a `download_video` audit entry.

**Request:**
```bash
curl -i -r 0-99 -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/clips/$CLIP_ID/video
```

**Response (`206 Partial Content`):**
```http
HTTP/1.1 206 Partial Content
accept-ranges: bytes
content-range: bytes 0-99/20605
content-length: 100
content-type: video/mp4
```

---

### `GET /files`

Serve files inside `DATA_DIR/uploads` or `DATA_DIR/outputs` using an HMAC-SHA256 signed URL (`p`, `uid`, `exp`, `sig`), with HTTP `Range` (`206`) and `?download=1` audit support. No `Authorization` header required.

**Request:**
```bash
curl -i -r 0-99 "http://127.0.0.1:8000$VIDEO_URL"
```

**Response (`206 Partial Content` for byte ranges, `200 OK` for full file):**
```http
HTTP/1.1 206 Partial Content
accept-ranges: bytes
content-range: bytes 0-99/20605
content-length: 100
content-type: video/mp4
```

---

## Processing & Runs Endpoints

### `POST /clips/{id}/process`

Validate transaction time, zone (`422 ZONE_NOT_FOUND` with valid zone IDs if `zone_polygon_norm` is unset and `atm_id` is unknown), and window cap (`(2 * window_sec + 2) * sample_fps <= 200`), queue a single-worker background job (priority `0`), and return `202 Accepted`.

**Request:**
```bash
curl -s -X POST http://127.0.0.1:8000/clips/$CLIP_ID/process \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"transaction_time":"2026-11-26T15:30:02","window_sec":2,"sample_fps":2.0,"tracker":"iou"}'
```

**Response (`202 Accepted`):**
```json
{
  "run_id": 1,
  "status": "queued"
}
```

---

### `GET /runs/{run_id}`

Poll run status (`queued` | `running` | `done` | `failed`), `stage`, `progress` (`0..1`), `progress_message`, `error_code`, `error_message`, `error_advice`, `link_low_margin`, and hydrated `result` (including per-frame `face_box` and `flag_scores`) when `done`.

**Request:**
```bash
curl -s http://127.0.0.1:8000/runs/1 -H "Authorization: Bearer $TOKEN"
```

**Response (`200 OK`):**
```json
{
  "run_id": 1,
  "clip_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "done",
  "stage": "done",
  "progress": 1.0,
  "progress_message": "Done (fake)",
  "error_code": null,
  "error_message": null,
  "error_advice": null,
  "transaction_time": "2026-11-26T15:30:02",
  "tx_offset_sec": 2.0,
  "window_sec": 2.0,
  "sample_fps": 2.0,
  "tracker": "iou",
  "atm_id": "atm_demo",
  "pipeline_mode": "fake",
  "served_from_demo_pack": false,
  "link_low_margin": false,
  "created_by": 2,
  "created_at": "2026-11-26T13:40:15.000000",
  "started_at": "2026-11-26T13:40:15.010000",
  "finished_at": "2026-11-26T13:40:15.250000",
  "result": { "...": "same shape as GET /runs/{run_id}/result" }
}
```

---

### `GET /clips/{id}/runs`

List all processing runs for a clip newest-first.

**Request:**
```bash
curl -s http://127.0.0.1:8000/clips/$CLIP_ID/runs -H "Authorization: Bearer $TOKEN"
```

**Response (`200 OK`):**
```json
[
  {
    "run_id": 1,
    "clip_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "done",
    "stage": "done",
    "progress": 1.0,
    "progress_message": "Done (fake)",
    "result": { "...": "hydrated RunResultOut" }
  }
]
```

---

### `GET /runs/{run_id}/result`

Return the hydrated `PipelineResult` for a completed run with signed `image_url`, `crop_url`, `enhanced_url`, `video_url`, `pipeline_mode`, `notice`, `link_low_margin`, `show_selection_reason`, and per-frame `face_box` and `flag_scores`.

**Request:**
```bash
curl -s http://127.0.0.1:8000/runs/1/result -H "Authorization: Bearer $TOKEN"
```

**Response (`200 OK`):**
```json
{
  "run_id": 1,
  "clip_id": "550e8400-e29b-41d4-a716-446655440000",
  "pipeline_mode": "fake",
  "served_from_demo_pack": false,
  "banner": "FAKE PIPELINE, DEMO DATA",
  "notice": "Possible matches only. A human investigator must verify every result.",
  "video_url": "/files?p=uploads%2F...&uid=2&exp=...&sig=...",
  "transaction_time": "2026-11-26T15:30:02",
  "person_track_id": 4,
  "best_frames": [
    {
      "frame_id": "142",
      "frame_path": "outputs/.../run_1/frame_142.jpg",
      "crop_path": "outputs/.../run_1/crop_142.jpg",
      "embedding_path": "outputs/.../run_1/emb_142.npy",
      "timestamp_sec": 5.68,
      "quality_score": 0.86,
      "reliability": "High",
      "flags": [],
      "flag_scores": null,
      "face_box": null,
      "enhanced": false,
      "enhancement": null,
      "metrics": {"sharpness": 0.88, "face_size": 112.0, "pose_yaw": 4.2, "illumination": 0.79, "occlusion": 0.05},
      "match_ready": null,
      "rank_reason": null,
      "selected": false,
      "image_url": "/files?...",
      "crop_url": "/files?...",
      "enhanced_url": null
    }
  ],
  "link_confidence": null,
  "link_reason": null,
  "link_low_margin": false,
  "selection_reason": null,
  "show_selection_reason": false,
  "timings_ms": null
}
```

---

## Search & Indexing Endpoints

### `POST /search`

Search processed run frames (`source: "run"`) and indexed clip faces (`source: "index"`) from **other** clips using a completed run frame's 512-d L2-normalised embedding. Persists the result in `searches` and logs a `search` audit entry.

Options:
- `best_per_clip` (default `true`): keep only the highest-scoring match per other clip.
- `include_short_tracks` (default `false`): include `short_track` indexed faces when `true`.

**Request:**
```bash
curl -s -X POST http://127.0.0.1:8000/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"run_id":1,"frame_id":"142","top_k":10,"best_per_clip":true,"include_short_tracks":false}'
```

**Response (`200 OK`):**
```json
{
  "search_id": 1,
  "run_id": 1,
  "frame_id": "142",
  "top_k": 10,
  "matches": [
    {
      "source": "run",
      "track_id": null,
      "short_track": false,
      "clip_id": "<other-clip-uuid>",
      "filename": "A_two.mp4",
      "run_id": 2,
      "index_id": null,
      "frame_id": "142",
      "t": null,
      "timestamp_sec": 5.68,
      "score": 0.978,
      "reliability": "High",
      "flags": [],
      "flag_scores": null,
      "crop_url": "/files?...",
      "frame_url": "/files?..."
    }
  ],
  "notice": "Possible matches only. A human investigator must verify every result.",
  "score_note": "uncalibrated similarity, tune on sample data",
  "scope": "frames from processed runs and indexed clips",
  "created_at": "2026-11-26T16:38:00.000000"
}
```

---

### `GET /searches/{id}`

Retrieve a saved search result with freshly signed `crop_url` and `frame_url` links (`null` if image missing).

**Request:**
```bash
curl -s http://127.0.0.1:8000/searches/1 -H "Authorization: Bearer $TOKEN"
```

**Response (`200 OK`):** Same JSON shape as `POST /search`.

---

### `POST /clips/{id}/index`

Queue a clip-wide face indexing job on the single-worker priority queue (priority `1`; processing runs are priority `0`). Also triggered automatically on `POST /clips` upload when `AUTO_INDEX_ON_UPLOAD=1`. Ranges over `600s` return `422 INDEX_RANGE_TOO_LONG`.

**Request (body optional):**
```bash
curl -s -X POST http://127.0.0.1:8000/clips/$CLIP_ID/index \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"start_sec":0,"end_sec":null,"sample_fps":1.0,"tracker":"iou","faces_per_track":3,"atm_id":"atm_demo"}'
```

**Response (`202 Accepted`):**
```json
{
  "index_id": 1,
  "status": "queued"
}
```

---

### `GET /clips/{id}/indexes`

List all indexing jobs for a clip newest-first.

**Request:**
```bash
curl -s http://127.0.0.1:8000/clips/$CLIP_ID/indexes -H "Authorization: Bearer $TOKEN"
```

**Response (`200 OK`):**
```json
[
  {
    "index_id": 1,
    "clip_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "done",
    "stage": "done",
    "progress": 1.0,
    "progress_message": "Done (fake)",
    "error_code": null,
    "error_message": null,
    "error_advice": null,
    "start_sec": 0.0,
    "end_sec": 4.0,
    "sample_fps": 1.0,
    "tracker": "iou",
    "faces_per_track": 3,
    "atm_id": "atm_demo",
    "total_embeddings": 5,
    "timings_ms": {"frames": 1.0, "detect_persons": 1.0, "track": 1.0, "faces": 1.0, "quality": 1.0, "save": 1.0},
    "pipeline_mode": "fake",
    "served_from_demo_pack": false,
    "created_by": 2,
    "created_at": "2026-11-27T07:19:22.000000",
    "started_at": "2026-11-27T07:19:22.010000",
    "finished_at": "2026-11-27T07:19:22.100000"
  }
]
```

---

### `GET /indexes/{index_id}`

Return index status, `stage`, `progress`, `progress_message`, `error_code`, `error_message`, `error_advice`, and `tracks` (with per-track `short_track` / `confidence_note`, `reason` when faceless, and `faces` with signed `crop_url` and `frame_url`, or `null` if missing).

**Request:**
```bash
curl -s http://127.0.0.1:8000/indexes/1 -H "Authorization: Bearer $TOKEN"
```

**Response (`200 OK`):**
```json
{
  "index_id": 1,
  "clip_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "done",
  "stage": "done",
  "progress": 1.0,
  "progress_message": "Done (fake)",
  "served_from_demo_pack": false,
  "total_embeddings": 5,
  "tracks": [
    {
      "track_id": 1,
      "first_t": 0.0,
      "last_t": 4.0,
      "n_observations": 6,
      "short_track": false,
      "confidence_note": null,
      "dwell_sec_in_zone": 4.0,
      "reason": null,
      "face_count": 2,
      "faces": [
        {
          "id": 1,
          "track_id": 1,
          "t": 0.0,
          "quality_score": 0.85,
          "reliability": "High",
          "match_ready": true,
          "flags": [],
          "flag_scores": null,
          "face_box": [10.0, 10.0, 74.0, 74.0],
          "short_track": false,
          "crop_url": "/files?...",
          "frame_url": "/files?..."
        }
      ]
    }
  ]
}
```

---

## Selection, Enhancement & Evidence PDF Endpoints

### `POST /runs/{run_id}/selection`

Replace the selected frames set for a completed run, validating all IDs belong to the run, and record a `frames_selected` audit entry.

**Request:**
```bash
curl -s -X POST http://127.0.0.1:8000/runs/1/selection \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"frame_ids":["142","158"]}'
```

**Response (`200 OK`):**
```json
{
  "run_id": 1,
  "selected_frame_ids": ["142", "158"]
}
```

---

### `POST /runs/{run_id}/frames/{frame_id}/enhance`

Non-destructively crop and upscale a full-frame evidence image (`scale`: `2` or `4`, `method`: `"lanczos"`, `crop_box`: `[x, y, w, h]` in full-frame pixels, `>= 8` px after clipping). Caches by `(frame, crop_box, method, scale)`, preserves original SHA-256, updates `frames.enhancement` / `enhanced=true`, and logs `frame_enhanced`. Invalid parameters return `422 ENHANCE_INVALID`.

**Request:**
```bash
curl -s -X POST http://127.0.0.1:8000/runs/1/frames/142/enhance \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"crop_box":[160,80,120,120],"scale":4,"method":"lanczos"}'
```

**Response (`200 OK`):**
```json
{
  "run_id": 1,
  "frame_id": "142",
  "original_url": "/files?p=outputs%2F...%2Fframe_142.jpg&...",
  "enhanced_url": "/files?p=outputs%2F...%2Fframe_142_enh_x4.jpg&...",
  "method": "lanczos",
  "scale": 4,
  "model_version": "lanczos_v1",
  "crop_box": [160, 80, 120, 120],
  "face_box": null,
  "search_embedding_source": "original",
  "cached": false
}
```

---

### `GET /runs/{run_id}/evidence.pdf`

Generate and download the ReportLab Platypus Evidence Sheet PDF (`application/pdf`), optionally including cross-clip search results (`?search_id=`). Logs `download_evidence` with `pdf_sha256` in audit details.

**Request:**
```bash
curl -s -o /tmp/evidence_test.pdf \
  -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/runs/1/evidence.pdf?search_id=1"
```

**Response (`200 OK`, `application/pdf`):**
```http
HTTP/1.1 200 OK
content-disposition: attachment; filename="evidence_EV-1.pdf"
content-type: application/pdf

%PDF-1.4 ...
```
