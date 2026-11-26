# PROJECT: PS04 ATM Face Evidence Finder ("Strix")

## Ownership
- `pipeline/`: **Mohit** (ML pipeline; do not edit `pipeline/ingest.py` or `pipeline/extract_frames.py` when owned by teammates)
- `backend/`: **Anshika**
- `frontend/`: **Aditi**

## Hard Rules
- **NEVER** use YOLOv8, Ultralytics, or any package that depends on them. After every install run: `pip list | grep -i ultralytics` (must print nothing).
- Prefer MIT/BSD/Apache libraries. Avoid AGPL/GPL.
- Python 3.10 or 3.11. Ubuntu, GTX 1650 with 4 GB VRAM. Always support CPU fallback (`device = "cuda" if available else "cpu"`). Catch CUDA out-of-memory and fall back.
- Person detection: `torchvision` Faster R-CNN MobileNetV3. Tracking: `supervision` ByteTrack or a simple IoU tracker. Faces/embeddings: InsightFace.
- Heavy libraries (`torch`, `cv2`, `insightface`, `onnxruntime`) are imported **INSIDE** functions, never at module top level of anything teammates import. `pipeline/__init__.py` stays empty. Teammates on Mac and Windows import `pipeline.fake_pipeline` without ML libraries installed.
- Use `pathlib` for all paths. Never commit `data/`, `models/`, `outputs/`, `.venv/`, `.env`.
- Output must follow `docs/sample_result.json` exactly. Do not change field names. Any contract change is only proposed, never made alone.
- Never use real personal data. Test with synthetic clips or consented practice clips.
- Enhanced images are labelled `ENHANCED` in the pixels; the original is never modified.
- Possible matches only. No automatic identification.
- Do not edit `backend/`, `frontend/`, `pipeline/ingest.py`, or `pipeline/extract_frames.py`.

## Workflow
- Make a short plan first. One phase per task. Write tests. Run them and show output before saying done.
- Keep functions short and commented so every line can be explained to judges.
- Pin only versions that have been verified working together.
