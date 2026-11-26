"""Check Python, PyTorch CUDA, ONNX Runtime providers, and OpenCV dnn_superres."""

import sys


def main() -> int:
    """Print environment and GPU diagnostics."""
    print(f"Python version: {sys.version.split()[0]}")

    try:
        import torch

        cuda_ok = torch.cuda.is_available()
        gpu_name = torch.cuda.get_device_name(0) if cuda_ok else "N/A"
        print(f"torch version: {torch.__version__}")
        print(f"torch.cuda.is_available(): {cuda_ok}")
        print(f"GPU name: {gpu_name}")
    except ImportError as exc:
        print(f"torch: NOT INSTALLED ({exc})")

    try:
        import onnxruntime as ort

        print(f"onnxruntime providers: {ort.get_available_providers()}")
    except ImportError as exc:
        print(f"onnxruntime: NOT INSTALLED ({exc})")

    try:
        import cv2

        has_superres = hasattr(cv2, "dnn_superres")
        print(f"cv2.dnn_superres available: {has_superres}")
    except ImportError as exc:
        print(f"cv2: NOT INSTALLED ({exc})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
