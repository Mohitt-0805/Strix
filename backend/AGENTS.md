# Strix backend: agent rules (owner: Anshika)

Project: PS04 ATM Face Evidence Finder ("Strix"). You are building ONLY the backend.
Full spec: @SPEC.md (read it before every phase). Also read ../PROJECT_RULES.md.

## Hard rules
- NEVER use or install YOLOv8, Ultralytics, or any package that depends on them. After every pip install run `pip list | grep -i ultralytics` (must print nothing) and `python scripts/check_no_ultralytics.py`.
- Prefer MIT/BSD/Apache libraries. No AGPL/GPL.
- Python 3.11 on a Mac with no GPU. The backend must run with USE_FAKE_PIPELINE=1 and without torch, cv2, insightface or onnxruntime installed. Never import those at module level, and never import them at all in backend code.
- Edit only: backend/**, backend/Dockerfile, docker-compose.yml. Never edit pipeline/, frontend/, docs/, requirements-api.txt, PROJECT_RULES.md or .env.example. If a change elsewhere is needed, write it in backend/PROPOSALS.md.
- Use pathlib for every path. Never commit data/, models/, outputs/, .venv/, .env, or any secret or default password.
- Pipeline output must match pipeline/contract.py. Do not rename its fields.
- Results are "possible matches" only. Every match response and every PDF carries the human-verification notice. No automatic identification.
- Originals are never modified. Enhanced images are labelled ENHANCED in the pixels.

## How to work
- One phase per request. Make a short plan first, implement, write tests, run them, run the server and call the endpoints, show the real output, then stop and wait.
- Never invent a library or model API. Check the installed version (`pip show`, `python -c "help(...)"`) before using unfamiliar calls.
- Keep functions short and commented so every line can be explained to judges.
- Do not add features outside SPEC.md.
