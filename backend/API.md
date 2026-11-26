# Strix Backend API

Base URL (local): `http://127.0.0.1:8000`

## Error Format

Every error response uses the uniform JSON shape:

```json
{
  "detail": "Not Found",
  "code": "NOT_FOUND"
}
```

## Endpoints

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
  "accepted_extensions": [
    "mp4",
    "avi",
    "mov",
    "mkv",
    "wmv",
    "flv",
    "mpeg",
    "mpg"
  ],
  "model_labels": [
    "FAKE PIPELINE"
  ],
  "display_tz": "Asia/Kolkata"
}
```
