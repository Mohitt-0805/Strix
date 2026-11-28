# Strix Backend

Owner: **Anshika**

FastAPI + SQLite backend for **PS04 ATM Face Evidence Finder ("Strix")**.
Runs locally on macOS/Windows with `USE_FAKE_PIPELINE=1` without installing `torch`, `cv2`, `insightface`, or `onnxruntime`.

> **Important:** All results are **possible matches only**. A human investigator must verify every result.

---

## 1. Prerequisites

- **Python 3.11** (recommended; tested on Python `3.11.18`)
- **FFmpeg & FFprobe** on `PATH` (checked at server startup via `/health`)

### Install FFmpeg

- **macOS (Homebrew):**
  ```bash
  brew install ffmpeg
  ffmpeg -version && ffprobe -version
  ```
- **Windows (winget / Chocolatey / Scoop):**
  ```powershell
  winget install Gyan.FFmpeg
  # Restart your terminal so ffmpeg and ffprobe are on PATH, then verify:
  ffmpeg -version
  ffprobe -version
  ```

---

## 2. Environment Setup

Run all commands from the **repository root**.

### macOS / Linux

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt
# Optional faster similarity search (falls back to NumPy automatically if omitted):
pip install faiss-cpu
# Verify no forbidden ultralytics packages are installed:
python scripts/check_no_ultralytics.py
```

### Windows (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
# Optional:
pip install faiss-cpu
python scripts\check_no_ultralytics.py
```

---

## 3. Configuration (`.env`)

Create a `.env` file at the **repository root** (copy `.env.example` as a starting point; never commit `.env`).

Generate a strong `JWT_SECRET` (minimum 32 characters — the server refuses to start without it):

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### `.env` Keys

| Key | Default | Description |
|---|---|---|
| `USE_FAKE_PIPELINE` | `1` | `1` runs the lightweight `pipeline.fake_pipeline` (no GPU/ML libs needed); `0` runs the real ML pipeline (or cached `DEMO_PACK_DIR` matches when set). |
| `DEMO_PACK_DIR` | *(unset)* | Optional path to a pre-computed demo pack folder containing `manifest.json` (used when `USE_FAKE_PIPELINE=0`). Cached runs match on clip filename, `atm_id`, `tx_offset_sec` (`transaction_time - clip_start_time` rounded to 3 decimals), and `window_sec`; cached indexes match on clip filename. External demo-pack files are copied into `DATA_DIR/outputs/` and responses/PDFs explicitly label `served_from_demo_pack=true`. |
| `DATA_DIR` | `./data` | Directory where `strix.db`, `uploads/`, and `outputs/` are stored (gitignored). |
| `JWT_SECRET` | *(required)* | Secret used to sign Bearer JWTs and HMAC `/files` URLs. Must be at least 32 characters. |
| `JWT_EXPIRE_MIN` | `480` | JWT expiration in minutes (default 8 hours). |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Comma-separated list of allowed browser origins. Never use `*`. |
| `AUTO_INDEX_ON_UPLOAD` | `1` | `1` automatically queues a background clip-indexing job (`clip_indexes`) after `POST /clips`; `0` disables auto-indexing. |
| `MAX_UPLOAD_MB` | `500` | Maximum allowed uploaded clip size in megabytes (`413 FILE_TOO_LARGE` above this). |
| `SIGNED_URL_TTL_SEC` | `900` | Lifetime in seconds for signed `/files` image and video URLs. |
| `DISPLAY_TZ` | `Asia/Kolkata` | Local timezone used when converting FFprobe `creation_time` and rendering PDF timestamps. |
| `EMBED_DIM` | `512` | Expected face embedding vector dimension. |

Example `.env`:

```dotenv
USE_FAKE_PIPELINE=1
DATA_DIR=./data
JWT_SECRET=replace-with-output-of-token_urlsafe-48
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
AUTO_INDEX_ON_UPLOAD=1
MAX_UPLOAD_MB=500
DISPLAY_TZ=Asia/Kolkata
```

### Demo Pack Cached Mode (`DEMO_PACK_DIR`)

When `USE_FAKE_PIPELINE=0` and `DEMO_PACK_DIR` points to a folder with a `manifest.json` (e.g. `DEMO_PACK_DIR=demo_pack`):

- `GET /config/public` reports `demo_pack_enabled: true`.
- Processing runs match the manifest on **exact clip filename**, **`atm_id`**, **`tx_offset_sec`** (`transaction_time - clip_start_time`, rounded to 3 decimals), and **`window_sec`** (falling back to live `run_pipeline` if any differs). Indexing matches on clip filename.
- Returned external asset files are copied into `DATA_DIR/outputs/<clip_id>/run_<run_id>/` (or `index_<index_id>/`) keeping filenames, and runs/indexes/evidence PDFs label results with `served_from_demo_pack: true` and the notice `"RESULT SERVED FROM A PRE-COMPUTED DEMO PACK (not computed live for this upload)"`.

---

## 4. Seed Users

Before starting the server for the first time, seed the `admin` and `investigator` accounts:

```bash
# Option A: pass passwords via environment variables
STRIX_ADMIN_PASSWORD="your-admin-pass" STRIX_INVESTIGATOR_PASSWORD="your-inv-pass" python backend/scripts/seed_users.py

# Option B: omit env vars to generate random passwords printed once to stdout
python backend/scripts/seed_users.py
```

> **Development schema changes:** No SQLite migrations are maintained during development. If the schema changes, delete `data/strix.db` (plus `data/strix.db-wal` / `data/strix.db-shm`) and re-run `backend/scripts/seed_users.py`.

---

## 5. Running the Server

### Local development

```bash
uvicorn backend.app.main:app --reload --port 8000
```

### Sharing on a local network (frontend teammate on another machine)

1. Find your machine's LAN IP (e.g., `192.168.1.42`).
2. Add your teammate's browser origin (the URL shown in their browser address bar, e.g. `http://192.168.1.50:5173`) to `CORS_ORIGINS` in `.env`:
   ```dotenv
   CORS_ORIGINS=http://localhost:5173,http://localhost:3000,http://192.168.1.50:5173
   ```
3. Bind Uvicorn to all interfaces:
   ```bash
   uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
   ```
4. Your teammate points the frontend API base URL at `http://192.168.1.42:8000`.

---

## 6. Running Tests & Smoke Test

Run the full pytest suite from the repository root:

```bash
pytest backend/tests -q
python scripts/check_no_ultralytics.py
```

Run the end-to-end smoke test against a running server:

```bash
STRIX_SMOKE_PASSWORD="your-inv-pass" python backend/scripts/smoke_test.py --base-url http://127.0.0.1:8000
```

---

## 7. Switching to the Real Pipeline

On the GPU / ML workstation (e.g., Ubuntu with CUDA/CPU weights and `requirements-ml.txt` installed):

1. Ensure the ML dependencies (`torch`, `torchvision`, `insightface`, `onnxruntime`, `opencv-python`) and model weights are installed, and verify `python scripts/check_no_ultralytics.py` passes.
2. Set `USE_FAKE_PIPELINE=0` in `.env`.
3. Start the server from the repo root:
   ```bash
   uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
   ```
   `GET /config/public` will switch `pipeline_mode` to `"real"`, omit the fake banner, and expose the real model labels.
