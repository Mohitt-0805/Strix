"""Verify that all Strix ML models load offline without network access."""

import os
from pathlib import Path
import socket
import sys
import urllib.request

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _block_network() -> None:
    def _deny(*_args: object, **_kwargs: object) -> None:
        raise OSError("Network access blocked for offline model verification")

    socket.create_connection = _deny  # type: ignore[assignment]
    urllib.request.urlopen = _deny  # type: ignore[assignment]


def main() -> int:
    _block_network()
    ok = True

    try:
        from pipeline.detect_track import load_person_detector

        load_person_detector(device="cpu")
        print("OK: Faster R-CNN MobileNetV3 person detector loaded offline.")
    except Exception as exc:
        print(f"MISSING/ERROR (person detector): {exc}")
        ok = False

    try:
        from pipeline.faces import get_face_app

        get_face_app()
        print("OK: InsightFace buffalo_l face app loaded offline.")
    except Exception as exc:
        print(f"MISSING/ERROR (face app): {exc}")
        ok = False

    try:
        from pipeline.occluders import get_model

        if get_model() is not None:
            print("OK: OpenCLIP ViT-B-32 (openai) loaded offline.")
        else:
            print("MISSING/ERROR (occluder CLIP): get_model() returned None")
            ok = False
    except Exception as exc:
        print(f"MISSING/ERROR (occluder CLIP): {exc}")
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
