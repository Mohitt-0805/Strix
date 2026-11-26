"""Contract and fake_pipeline tests."""

from pathlib import Path
import sys

from PIL import Image

from pipeline.contract import Enhancement, Frame, Metrics, PipelineResult, load_result
import pipeline.fake_pipeline as fake_pipeline


SAMPLE_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "sample_result.json"


def test_fake_pipeline_does_not_import_ml_libs() -> None:
    """Importing pipeline.fake_pipeline must not import torch or cv2."""
    assert "torch" not in sys.modules
    assert "cv2" not in sys.modules


def test_load_sample_result_and_roundtrip() -> None:
    """Load docs/sample_result.json, validate types, and round-trip through JSON."""
    result = load_result(SAMPLE_PATH)
    assert isinstance(result, PipelineResult)
    assert result.clip_id == "atm_clip_03"
    assert result.transaction_time == "2026-11-22T14:32:10"
    assert result.person_track_id == 4
    assert len(result.best_frames) == 3

    frame1, frame2, _ = result.best_frames
    assert isinstance(frame1, Frame)
    assert isinstance(frame1.metrics, Metrics)
    assert frame1.enhanced is False
    assert frame1.enhancement is None

    assert frame2.enhanced is True
    assert isinstance(frame2.enhancement, Enhancement)
    assert frame2.enhancement.method == "espcn"
    assert frame2.enhancement.scale == 4
    assert frame2.enhancement.search_embedding_source == "original"

    dumped = result.model_dump_json()
    reloaded = PipelineResult.model_validate_json(dumped)
    assert reloaded == result


def test_fake_pipeline_run_sets_clip_id() -> None:
    """run() derives clip_id from the input clip filename."""
    result = fake_pipeline.run(Path("data/samples/test_clip_99.mp4"), tx_offset_sec=12.5)
    assert result.clip_id == "test_clip_99"
    assert len(result.best_frames) == 3


def test_fake_enhance_writes_separate_file_without_touching_original(tmp_path: Path) -> None:
    """fake_enhance() saves <name>_enh_x<scale>.jpg and leaves the original untouched."""
    src = tmp_path / "sample_face.png"
    Image.new("RGB", (100, 100), color=(40, 80, 120)).save(src)
    original_bytes = src.read_bytes()

    out = fake_pipeline.fake_enhance(src, crop_box=[10, 20, 30, 40], scale=4)

    assert out == tmp_path / "sample_face_enh_x4.jpg"
    assert out.exists()
    assert src.read_bytes() == original_bytes

    with Image.open(out) as enhanced_img:
        assert enhanced_img.size == (120, 160)
