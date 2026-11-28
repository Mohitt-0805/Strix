"""Tests for scripts/onboard_clips.py using tiny synthetic ffmpeg videos."""

import csv
from pathlib import Path
import subprocess

import pytest

from scripts.onboard_clips import MANIFEST_COLUMNS, onboard_folder


def _run_ffmpeg(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, f"ffmpeg failed: {' '.join(cmd)}\n{proc.stderr}"


def test_onboard_synthetic_containers_vfr_rotated_and_nonvideo(tmp_path: Path) -> None:
    """Onboard mp4, avi, mkv, VFR, and rotated clips plus a non-video file."""
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    out_dir = tmp_path / "onboarding_out"

    # 1. Standard MP4 clip (2s, 10fps, with creation_time metadata).
    _run_ffmpeg([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=2",
        "-metadata", "creation_time=2026-11-27T10:00:00Z",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(clips_dir / "clip_cfr.mp4"),
    ])

    # 2. AVI container.
    _run_ffmpeg([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=2",
        "-c:v", "mpeg4",
        str(clips_dir / "clip_box.avi"),
    ])

    # 3. MKV container.
    _run_ffmpeg([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(clips_dir / "clip_box.mkv"),
    ])

    # 4. Variable-frame-rate MP4 (keeps every 3rd frame in first half, all in second half).
    _run_ffmpeg([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=30:duration=2",
        "-vf", r"select=not(mod(n\,3))+gt(t\,1),setpts=PTS", "-fps_mode", "vfr",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(clips_dir / "clip_vfr.mp4"),
    ])

    # 5. Rotated MP4 (display dimensions swap 160x120 -> 120x160).
    _run_ffmpeg([
        "ffmpeg", "-y", "-noautorotate", "-display_rotation:v:0", "90",
        "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(clips_dir / "clip_rot.mp4"),
    ])

    # 6. Non-video file.
    (clips_dir / "notes.txt").write_text("organiser readme\n", encoding="utf-8")

    manifest_before = (
        Path("data/samples/manifest.csv").read_bytes()
        if Path("data/samples/manifest.csv").exists()
        else None
    )

    res = onboard_folder(clips_dir, out_dir=out_dir, convert=False, normalised_dir=tmp_path / "norm")

    assert res["non_video_files"] == ["notes.txt"]
    assert len(res["records"]) == 5

    by_name = {r["clip_name"]: r for r in res["records"]}
    assert all("OK" in r["readable"] for r in res["records"])
    assert "avi" in by_name["clip_box.avi"]["probe"]["container"]
    assert "matroska" in by_name["clip_box.mkv"]["probe"]["container"]
    assert by_name["clip_cfr.mp4"]["probe"]["creation_time_ist"] == "2026-11-27T15:30:00+05:30"
    assert by_name["clip_vfr.mp4"]["probe"]["vfr_suspected"] is True

    rot_probe = by_name["clip_rot.mp4"]["probe"]
    assert abs(rot_probe["rotation"]) % 180 == 90
    assert rot_probe["display_width"] == 120 and rot_probe["display_height"] == 160

    for r in res["records"]:
        assert r["contact_sheet"] is not None
        cs_path = Path(r["contact_sheet"])
        assert cs_path.exists()
        assert cs_path.resolve().is_relative_to(out_dir.resolve())
        assert "heuristic" in r["camera"]

    report_path = Path(res["report_path"])
    assert report_path.exists()
    report_txt = report_path.read_text(encoding="utf-8")
    assert "| clip | container | codec | resolution |" in report_txt
    assert "## Problems" in report_txt
    assert "notes.txt" in report_txt

    draft_path = Path(res["manifest_draft_path"])
    assert draft_path.exists()
    with draft_path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 5
    assert list(rows[0].keys()) == MANIFEST_COLUMNS
    assert rows[0]["window_sec"] == "10"
    assert rows[0]["tx_sec"] == ""
    assert rows[0]["expect_link"] == ""
    assert rows[0]["notes"] == "TO FILL BY HUMAN"
    assert any(r["atm_id"] == "cam_clip_cfr" for r in rows)

    if manifest_before is not None:
        assert Path("data/samples/manifest.csv").read_bytes() == manifest_before


def test_onboard_unreadable_prints_command_and_converts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Unreadable file logs normalisation command; --convert writes normalised mp4 without touching original."""
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    src = clips_dir / "broken.mp4"
    # Create a real mp4 but stub readability to fail once before conversion so ffmpeg --convert produces a real mp4.
    _run_ffmpeg([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=128x96:rate=10:duration=1",
        "-c:v", "mpeg4",
        str(src),
    ])
    orig_bytes = src.read_bytes()

    import scripts.onboard_clips as oc_mod

    real_check = oc_mod._check_readability

    def _fail_original_only(path: Path, dur: float) -> tuple[bool, str]:
        if path.resolve() == src.resolve():
            return False, "Simulated decode failure"
        return real_check(path, dur)

    monkeypatch.setattr(oc_mod, "_check_readability", _fail_original_only)

    norm_dir = tmp_path / "normalised"
    res = oc_mod.onboard_folder(clips_dir, out_dir=tmp_path / "out", convert=True, normalised_dir=norm_dir)

    stdout = capsys.readouterr().out
    assert "libx264" in stdout and "yuv420p" in stdout and "-fps_mode cfr" in stdout
    converted = norm_dir / "broken.mp4"
    assert converted.exists()
    assert src.read_bytes() == orig_bytes
    assert "OK" in res["records"][0]["readable"]
    assert "converted" in res["records"][0]["notes"]
