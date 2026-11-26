"""Placeholder frame, crop, and embedding asset materializer for fake mode."""

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from pipeline.contract import Enhancement, Frame, PipelineResult


def person_key_from_filename(filename: str) -> str:
    """Extract person key from filename stem before the first underscore."""
    stem = Path(filename).stem.strip()
    if not stem:
        return "unknown"
    return stem.split("_", 1)[0] or stem


def _seeded_rng(seed_text: str) -> np.random.Generator:
    """Create a deterministic NumPy RNG from an arbitrary seed string."""
    digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
    seed_int = int.from_bytes(digest[:8], "big")
    return np.random.default_rng(seed_int)


def generate_person_embedding(
    person_key: str,
    noise_key: str,
    embed_dim: int = 512,
    noise_scale: float = 0.15,
) -> np.ndarray:
    """Return L2-normalised (person_vector + noise_scale * noise) float32 vector."""
    person_vec = _seeded_rng(f"person:{person_key}").standard_normal(embed_dim)
    noise_vec = _seeded_rng(f"noise:{noise_key}").standard_normal(embed_dim)
    combined = person_vec + noise_scale * noise_vec
    norm = float(np.linalg.norm(combined))
    if norm <= 0.0:
        combined = np.ones(embed_dim, dtype=np.float32)
        norm = float(np.linalg.norm(combined))
    return (combined / norm).astype(np.float32)


def _write_placeholder_jpg(dest: Path, size: tuple[int, int], label: str, bg: tuple[int, int, int]) -> None:
    """Create a synthetic RGB JPEG with a human-readable label."""
    img = Image.new("RGB", size, color=bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(8, 8), (size[0] - 9, size[1] - 9)], outline=(200, 210, 220), width=2)
    draw.text((20, 20), label, fill=(255, 255, 255))
    img.save(dest, format="JPEG", quality=90)


def _write_placeholder_enhanced(
    src_frame: Path,
    dest: Path,
    crop_box: list[int],
    scale: int,
) -> None:
    """Create an enhanced JPEG from src_frame with 'ENHANCED' stamped in pixels."""
    x, y, w, h = crop_box
    with Image.open(src_frame) as img:
        img_w, img_h = img.size
        cx = max(0, min(x, img_w - 8))
        cy = max(0, min(y, img_h - 8))
        cw = max(8, min(w, img_w - cx))
        ch = max(8, min(h, img_h - cy))
        cropped = img.convert("RGB").crop((cx, cy, cx + cw, cy + ch))
        upscaled = cropped.resize(
            (cw * scale, ch * scale),
            resample=Image.Resampling.LANCZOS,
        )
        draw = ImageDraw.Draw(upscaled)
        draw.rectangle([(4, 4), (74, 20)], fill=(0, 0, 0))
        draw.text((8, 7), "ENHANCED", fill=(255, 255, 0))
        upscaled.save(dest, format="JPEG", quality=90)


def materialize_fake_assets(
    result: PipelineResult,
    *,
    clip_id: str,
    run_id: int,
    original_filename: str,
    data_dir: Path,
    embed_dim: int = 512,
) -> PipelineResult:
    """Write per-run placeholder JPGs and L2-normalised .npy embeddings and rewrite paths."""
    run_dir = data_dir.resolve() / "outputs" / clip_id / f"run_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    person_key = person_key_from_filename(original_filename)

    updated_frames: list[Frame] = []
    for idx, frame in enumerate(result.best_frames):
        tag = str(frame.frame_id)
        frame_path = run_dir / f"frame_{tag}.jpg"
        crop_path = run_dir / f"crop_{tag}.jpg"
        emb_path = run_dir / f"emb_{tag}.npy"

        _write_placeholder_jpg(
            frame_path,
            (640, 480),
            f"FAKE FRAME {tag}\nclip={clip_id}\nperson={person_key}",
            bg=(28, 42, 58),
        )
        _write_placeholder_jpg(
            crop_path,
            (160, 160),
            f"FAKE CROP {tag}\nperson={person_key}",
            bg=(48, 68, 92),
        )

        embedding = generate_person_embedding(
            person_key=person_key,
            noise_key=f"{clip_id}:{run_id}:{tag}:{idx}",
            embed_dim=embed_dim,
        )
        np.save(emb_path, embedding)

        enhancement_update: Enhancement | None = frame.enhancement
        if frame.enhanced and frame.enhancement is not None:
            enh_path = run_dir / f"frame_{tag}_enh_x{frame.enhancement.scale}.jpg"
            _write_placeholder_enhanced(
                frame_path,
                enh_path,
                frame.enhancement.crop_box,
                frame.enhancement.scale,
            )
            enhancement_update = frame.enhancement.model_copy(
                update={"enhanced_path": str(enh_path)}
            )

        updated_frames.append(
            frame.model_copy(
                update={
                    "frame_path": str(frame_path),
                    "crop_path": str(crop_path),
                    "embedding_path": str(emb_path),
                    "enhancement": enhancement_update,
                }
            )
        )

    return result.model_copy(update={"best_frames": updated_frames})
