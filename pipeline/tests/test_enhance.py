"""Tests for pipeline.enhance and aligned fake_pipeline.fake_enhance."""

from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from pipeline.contract import Enhancement


def test_lazy_imports_enhance() -> None:
    """Importing pipeline.enhance must not import cv2 or numpy."""
    code = (
        "import sys; "
        "import pipeline.enhance; "
        "loaded = [m for m in ('cv2', 'numpy') if m in sys.modules]; "
        "assert not loaded, f'Unexpected heavy imports: {loaded}'"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr or res.stdout


def test_enhance_frame_original_untouched_size_banner_and_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify original bytes unchanged, output size, red top banner, and cache hit."""
    import cv2
    from pipeline import enhance as enh_mod

    src = tmp_path / "frame_001.jpg"
    img = np.full((120, 160, 3), (80, 140, 100), dtype=np.uint8)
    cv2.imwrite(str(src), img)
    orig_bytes = src.read_bytes()

    crop_box = [20, 15, 50, 40]
    enh = enh_mod.enhance_frame(src, crop_box, method="lanczos", scale=4)

    # (a) Original file bytes identical.
    assert src.read_bytes() == orig_bytes
    assert isinstance(enh, Enhancement)
    out_path = Path(enh.enhanced_path)
    assert out_path.exists()
    assert out_path.name == "frame_001_enh_x4.jpg"

    # (b) Output size equals crop size * scale.
    out_img = cv2.imread(str(out_path))
    assert out_img is not None
    assert out_img.shape[:2] == (40 * 4, 50 * 4)

    # (c) Top banner region is mostly red (R >> G, B) and differs from plain resize.
    plain = cv2.resize(img[15:55, 20:70], (50 * 4, 40 * 4), interpolation=cv2.INTER_LANCZOS4)
    top_strip = out_img[:12, :, :]  # BGR
    assert float(np.mean(top_strip[:, :, 2])) > 150.0  # R channel high
    assert float(np.mean(top_strip[:, :, 0])) < 60.0   # B channel low
    assert float(np.mean(np.abs(top_strip.astype(np.float32) - plain[:12, :, :].astype(np.float32)))) > 40.0

    # (d) Second call hits cache without calling the upscale function again.
    calls = 0

    def _boom_upscale(crop: object, scale: int) -> object:
        nonlocal calls
        calls += 1
        raise AssertionError("Cache miss: upscale should not be called")

    monkeypatch.setitem(enh_mod.ENHANCE_METHODS, "lanczos", (_boom_upscale, "lanczos_v1"))
    cached = enh_mod.enhance_frame(src, crop_box, method="lanczos", scale=4)
    assert calls == 0
    assert cached == enh


def test_enhance_frame_invalid_args_raise_value_error(tmp_path: Path) -> None:
    """Invalid scale, unknown method, and empty/tiny box raise ValueError."""
    import cv2
    from pipeline.enhance import enhance_frame

    src = tmp_path / "small.jpg"
    cv2.imwrite(str(src), np.zeros((60, 80, 3), dtype=np.uint8))

    with pytest.raises(ValueError):
        enhance_frame(src, [0, 0, 40, 40], scale=3)
    with pytest.raises(ValueError, match="Known methods"):
        enhance_frame(src, [0, 0, 40, 40], method="espcn", scale=4)
    with pytest.raises(ValueError):
        enhance_frame(src, [100, 100, 20, 20], scale=4)
    with pytest.raises(ValueError):
        enhance_frame(src, [0, 0, 4, 4], scale=4)


def test_fake_and_real_enhance_parity(tmp_path: Path) -> None:
    """fake_enhance and enhance_frame produce identical filenames and Enhancement fields."""
    from PIL import Image
    from pipeline.enhance import enhance_frame
    from pipeline.fake_pipeline import fake_enhance

    real_dir = tmp_path / "real"
    fake_dir = tmp_path / "fake"
    real_dir.mkdir()
    fake_dir.mkdir()

    src_real = real_dir / "sample.jpg"
    src_fake = fake_dir / "sample.jpg"
    Image.new("RGB", (100, 80), color=(90, 110, 130)).save(src_real, format="JPEG")
    Image.new("RGB", (100, 80), color=(90, 110, 130)).save(src_fake, format="JPEG")

    e_real = enhance_frame(src_real, [10, 10, 40, 30], scale=2)
    e_fake = fake_enhance(src_fake, [10, 10, 40, 30], scale=2)

    assert Path(e_real.enhanced_path).name == Path(e_fake.enhanced_path).name == "sample_enh_x2.jpg"
    assert e_real.method == e_fake.method == "lanczos"
    assert e_real.scale == e_fake.scale == 2
    assert e_real.model_version == e_fake.model_version == "lanczos_v1"
    assert e_real.crop_box == e_fake.crop_box == [10, 10, 40, 30]
    assert e_real.search_embedding_source == e_fake.search_embedding_source == "original"
