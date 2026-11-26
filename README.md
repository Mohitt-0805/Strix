# Strix (PS04 ATM Face Evidence Finder)

## Team Ownership
- `pipeline/` — Mohit
- `backend/` — Anshika
- `frontend/` — Aditi

## Git Hooks Setup (Required for All Teammates)
Enable the repo's `pre-push` hook (which blocks pushing if `ultralytics` is installed):

```bash
git config core.hooksPath .githooks
```

## Ubuntu Setup

1. Create and activate a Python 3.10 or 3.11 virtual environment:
   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   ```
   *(If `python3.11` is not installed globally, you can create it with `uv venv --python 3.11 --seed .venv`.)*

2. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

3. **Backend / Frontend teammates (lightweight, no ML)**:
   ```bash
   pip install -r requirements-api.txt
   ```

4. **ML Pipeline (Ubuntu + NVIDIA GPU)**:
   - Install PyTorch with CUDA first from the official selector at <https://pytorch.org/get-started/locally/>.
   - Then install ML dependencies:
     ```bash
     pip install -r requirements-ml.txt
     ```
   - Verify no `ultralytics` and inspect GPU/providers:
     ```bash
     python scripts/check_no_ultralytics.py
     python scripts/check_gpu.py
     ```
