"""Unit and integration tests for CCTV video ingestion and transcoding."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

import pipeline.ingest as ingest
from pipeline.ingest import ACCEPTED_EXTENSIONS, IngestResult, check_and_convert, parse_fps

HAS_FFMPEG_AND_FFPROBE = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def test_ingest_module_never_imports_heavy_ml_libs() -> None:
    """Importing pipeline.ingest must never import torch, cv2, insightface, or onnxruntime."""
    prohibited = ["torch", "cv2", "insightface", "onnxruntime"]
    for mod in prohibited:
        assert mod not in sys.modules, f"Forbidden heavy library '{mod}' was imported by pipeline.ingest"


def test_accepted_extensions_coverage() -> None:
    """Validate that all 8 required CCTV video extensions are accepted."""
    required = {"mp4", "avi", "mov", "mkv", "wmv", "flv", "mpeg", "mpg"}
    assert required.issubset(ACCEPTED_EXTENSIONS)


def test_ingest_result_pydantic_schema(tmp_path: Path) -> None:
    """Validate IngestResult Pydantic schema, defaults, and JSON round-trip."""
    dummy_path = tmp_path / "test.mp4"
    result = IngestResult(
        ok=True,
        output_path=dummy_path,
        codec="h264",
        container="mov,mp4,m4a,3gp,3g2,mj2",
        width=1920,
        height=1080,
        fps=25.0,
        duration_sec=12.5,
        converted=False,
    )

    assert result.ok is True
    assert result.output_path == dummy_path
    assert result.codec == "h264"
    assert result.converted is False
    assert result.error_code is None
    assert result.advice is None

    # Test JSON serialization / deserialization roundtrip
    dumped = result.model_dump_json()
    reloaded = IngestResult.model_validate_json(dumped)
    assert reloaded == result


def test_parse_fps_rational_and_edge_cases() -> None:
    """Test parse_fps with various rational fractions and edge inputs."""
    assert parse_fps("30/1") == 30.0
    assert parse_fps("25/1") == 25.0
    assert parse_fps("30000/1001") == 29.97
    assert parse_fps("10/2") == 5.0
    assert parse_fps("0/0") is None
    assert parse_fps("invalid") is None
    assert parse_fps("") is None
    assert parse_fps(None) is None


def test_unsupported_extension(tmp_path: Path) -> None:
    """Files with non-video or untrusted extensions must be rejected."""
    bad_file = tmp_path / "malicious.exe"
    bad_file.write_text("dummy")

    res = check_and_convert(bad_file, tmp_path / "out")
    assert res.ok is False
    assert res.error_code == "UNSUPPORTED_EXTENSION"
    assert "exe" in (res.advice or "")
    assert res.converted is False


def test_file_not_found(tmp_path: Path) -> None:
    """Non-existent video files must return FILE_NOT_FOUND error with advice."""
    missing = tmp_path / "does_not_exist.mp4"
    res = check_and_convert(missing, tmp_path / "out")
    assert res.ok is False
    assert res.error_code == "FILE_NOT_FOUND"
    assert res.advice is not None
    assert "not exist" in res.advice.lower()


def test_not_a_file_error(tmp_path: Path) -> None:
    """Providing a directory instead of a file must return NOT_A_FILE."""
    sub_dir = tmp_path / "nested_dir.mp4"
    sub_dir.mkdir()

    res = check_and_convert(sub_dir, tmp_path / "out")
    assert res.ok is False
    assert res.error_code == "NOT_A_FILE"
    assert res.advice is not None


def test_empty_file_error(tmp_path: Path) -> None:
    """Zero-byte video files must return EMPTY_FILE."""
    empty_file = tmp_path / "empty_recording.mp4"
    empty_file.touch()

    res = check_and_convert(empty_file, tmp_path / "out")
    assert res.ok is False
    assert res.error_code == "EMPTY_FILE"
    assert res.advice is not None
    assert "0 bytes" in res.advice


def test_missing_ffprobe_binary(tmp_path: Path) -> None:
    """If ffprobe is not on PATH, return FFPROBE_MISSING."""
    video = tmp_path / "cctv.mp4"
    video.write_bytes(b"dummy video data")

    with patch("shutil.which", return_value=None):
        res = check_and_convert(video, tmp_path / "out")
        assert res.ok is False
        assert res.error_code == "FFPROBE_MISSING"
        assert "ffprobe" in (res.advice or "")


def test_ffprobe_timeout_error(tmp_path: Path) -> None:
    """When ffprobe times out, return FFPROBE_TIMEOUT."""
    video = tmp_path / "cctv.mp4"
    video.write_bytes(b"dummy video data")

    with patch("shutil.which", return_value="/usr/bin/ffprobe"), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=30)):
        res = check_and_convert(video, tmp_path / "out")
        assert res.ok is False
        assert res.error_code == "FFPROBE_TIMEOUT"
        assert "timed out" in (res.advice or "").lower()


def test_unreadable_file_probe_error(tmp_path: Path) -> None:
    """When ffprobe returns non-zero, return UNREADABLE_FILE."""
    video = tmp_path / "cctv.mp4"
    video.write_bytes(b"dummy video data")

    mock_fail = subprocess.CompletedProcess(args=["ffprobe"], returncode=1, stdout="", stderr="Corrupted NAL")
    with patch("shutil.which", return_value="/usr/bin/ffprobe"), \
         patch("subprocess.run", return_value=mock_fail):
        res = check_and_convert(video, tmp_path / "out")
        assert res.ok is False
        assert res.error_code == "UNREADABLE_FILE"
        assert "could not read" in (res.advice or "").lower()


def test_no_video_stream(tmp_path: Path) -> None:
    """Footage with no video streams returns NO_VIDEO_STREAM."""
    video = tmp_path / "audio_only.mp4"
    video.write_bytes(b"dummy data")

    mock_json = json.dumps({"streams": [], "format": {"format_name": "mp4", "duration": "10.0"}})
    mock_proc = subprocess.CompletedProcess(args=["ffprobe"], returncode=0, stdout=mock_json, stderr="")

    with patch("shutil.which", return_value="/usr/bin/ffprobe"), \
         patch("subprocess.run", return_value=mock_proc):
        res = check_and_convert(video, tmp_path / "out")
        assert res.ok is False
        assert res.error_code == "NO_VIDEO_STREAM"
        assert "No video stream" in (res.advice or "")


def test_unknown_or_missing_codec(tmp_path: Path) -> None:
    """Proprietary DVR exports without recognizable codec return UNKNOWN_CODEC."""
    video = tmp_path / "cctv.mp4"
    video.write_bytes(b"dummy data")

    mock_json = json.dumps({
        "streams": [{"codec_name": None, "width": 1280, "height": 720}],
        "format": {"format_name": "dav", "duration": "15.0"}
    })
    mock_proc = subprocess.CompletedProcess(args=["ffprobe"], returncode=0, stdout=mock_json, stderr="")

    with patch("shutil.which", return_value="/usr/bin/ffprobe"), \
         patch("subprocess.run", return_value=mock_proc):
        res = check_and_convert(video, tmp_path / "out")
        assert res.ok is False
        assert res.error_code == "UNKNOWN_CODEC"
        assert "Proprietary or unrecognized" in (res.advice or "")


def test_zero_duration_clip(tmp_path: Path) -> None:
    """Clips with 0 duration return ZERO_DURATION error with guidance."""
    video = tmp_path / "zero_sec.mp4"
    video.write_bytes(b"dummy data")

    mock_json = json.dumps({
        "streams": [{"codec_name": "h264", "width": 1280, "height": 720, "duration": "0.0"}],
        "format": {"format_name": "mp4", "duration": "0.0"}
    })
    mock_proc = subprocess.CompletedProcess(args=["ffprobe"], returncode=0, stdout=mock_json, stderr="")

    with patch("shutil.which", return_value="/usr/bin/ffprobe"), \
         patch("subprocess.run", return_value=mock_proc):
        res = check_and_convert(video, tmp_path / "out")
        assert res.ok is False
        assert res.error_code == "ZERO_DURATION"
        assert "0.0s duration" in (res.advice or "")


def test_h264_mp4_passthrough_without_conversion(tmp_path: Path) -> None:
    """An existing H.264 MP4 clip is verified and passed through directly (converted=False)."""
    video = tmp_path / "atm_cctv.mp4"
    video.write_bytes(b"dummy mp4 data")

    mock_json = json.dumps({
        "streams": [{
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "25/1",
            "duration": "45.5"
        }],
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "45.5"}
    })
    mock_proc = subprocess.CompletedProcess(args=["ffprobe"], returncode=0, stdout=mock_json, stderr="")

    with patch("shutil.which", return_value="/usr/bin/ffprobe"), \
         patch("subprocess.run", return_value=mock_proc):
        res = check_and_convert(video, tmp_path / "out")
        assert res.ok is True
        assert res.converted is False
        assert res.output_path == video
        assert res.codec == "h264"
        assert res.width == 1920
        assert res.height == 1080
        assert res.fps == 25.0
        assert res.duration_sec == 45.5


def test_transcode_avi_to_h264_mp4(tmp_path: Path) -> None:
    """AVI container footage is transcoded to H.264 MP4 while preserving original."""
    video = tmp_path / "atm_cctv.avi"
    video.write_bytes(b"dummy avi data")
    out_dir = tmp_path / "out"

    probe_raw = json.dumps({
        "streams": [{
            "codec_name": "mpeg4",
            "width": 704,
            "height": 576,
            "avg_frame_rate": "20/1",
            "duration": "30.0"
        }],
        "format": {"format_name": "avi", "duration": "30.0"}
    })
    conv_probe = json.dumps({
        "streams": [{
            "codec_name": "h264",
            "width": 704,
            "height": 576,
            "avg_frame_rate": "20/1",
            "duration": "30.0"
        }],
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "30.0"}
    })

    def mock_subprocess(cmd, *args, **kwargs):
        cmd_str = " ".join(str(c) for c in cmd)
        if "-show_entries" in cmd_str or "ffprobe" in cmd_str:
            target = str(cmd[-1])
            if "converted" in target:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=conv_probe, stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=probe_raw, stderr="")
        elif "-crf" in cmd_str or "ffmpeg" in cmd_str:
            # Simulate ffmpeg creating the converted file
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"converted h264 bytes")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("shutil.which", return_value="/usr/bin/tool"), \
         patch("subprocess.run", side_effect=mock_subprocess):
        res = check_and_convert(video, out_dir)
        assert res.ok is True
        assert res.converted is True
        assert res.output_path == out_dir / "atm_cctv_converted.mp4"
        assert res.output_path.exists()
        assert res.codec == "h264"
        # Original file is preserved untouched
        assert video.exists()
        assert video.read_bytes() == b"dummy avi data"


@pytest.mark.skipif(
    not HAS_FFMPEG_AND_FFPROBE,
    reason="ffmpeg and ffprobe must be on system PATH to test corrupted file detection",
)
def test_corrupted_file_handling(tmp_path: Path) -> None:
    """Files with corrupted or invalid headers must return UNREADABLE_FILE."""
    corrupt_file = tmp_path / "corrupt_stream.mp4"
    corrupt_file.write_bytes(b"\x00\x01\x02\x03\x04\x05GARBAGE_PAYLOAD\xff\xfe")

    res = check_and_convert(corrupt_file, tmp_path / "out")
    assert res.ok is False
    assert res.error_code in ("UNREADABLE_FILE", "FFPROBE_TIMEOUT")
    assert res.advice is not None


@pytest.mark.skipif(
    not HAS_FFMPEG_AND_FFPROBE,
    reason="ffmpeg and ffprobe must be on system PATH to generate and test synthetic clips",
)
@pytest.mark.parametrize(
    "format_ext,vcodec",
    [
        ("mp4", "libx264"),
        ("avi", "mpeg4"),
        ("mov", "libx264"),
        ("mkv", "mpeg4"),
    ],
)
def test_synthetic_clips_ingest(tmp_path: Path, format_ext: str, vcodec: str) -> None:
    """Generate synthetic clips with testsrc and verify check_and_convert across formats."""
    src_clip = tmp_path / f"synthetic_cctv.{format_ext}"
    out_dir = tmp_path / "converted_out"

    # Generate 1-second synthetic CCTV clip via ffmpeg
    gen_cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=1:size=320x240:rate=10",
        "-c:v",
        vcodec,
        str(src_clip),
    ]
    gen_proc = subprocess.run(gen_cmd, capture_output=True, text=True, timeout=30)
    assert gen_proc.returncode == 0, f"Failed to generate synthetic clip: {gen_proc.stderr}"
    assert src_clip.is_file()
    orig_bytes = src_clip.read_bytes()

    res = check_and_convert(src_clip, out_dir)
    assert res.ok is True, f"check_and_convert failed: {res.error_code} - {res.advice}"
    assert res.width == 320
    assert res.height == 240
    assert res.duration_sec is not None and res.duration_sec > 0

    # Verify original file was never modified or deleted
    assert src_clip.exists()
    assert src_clip.read_bytes() == orig_bytes

    if format_ext == "mp4" and vcodec == "libx264":
        # Already H.264 MP4: no conversion needed
        assert res.converted is False
        assert res.output_path == src_clip
    else:
        # Other container or codec: converted to H.264 MP4
        assert res.converted is True
        assert res.output_path is not None
        assert res.output_path.exists()
        assert res.output_path.suffix.lower() == ".mp4"
        assert res.codec.lower() in ("h264", "avc", "avc1")
