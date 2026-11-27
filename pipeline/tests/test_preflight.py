"""Tests for scripts/preflight.py check logic and exit codes."""

from pathlib import Path
import shutil
import pytest

from scripts import preflight


def test_disk_space_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disk space returns FAIL < 2 GB, WARN < 5 GB, PASS >= 5 GB."""
    gb = 1024 ** 3
    monkeypatch.setattr(shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(100 * gb, 99 * gb, 1 * gb))
    assert preflight.check_disk_space()[1] == "FAIL"

    monkeypatch.setattr(shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(100 * gb, 97 * gb, 3 * gb))
    assert preflight.check_disk_space()[1] == "WARN"

    monkeypatch.setattr(shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(100 * gb, 80 * gb, 20 * gb))
    assert preflight.check_disk_space()[1] == "PASS"


def test_git_status_fails_on_tracked_media(monkeypatch: pytest.MonkeyPatch) -> None:
    """check_git_status returns FAIL if any media file is tracked."""
    class _Proc:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def _fake_run(cmd: list[str], **_kw: object) -> _Proc:
        if "rev-parse" in cmd:
            return _Proc("mohit-ml\n")
        if "status" in cmd:
            return _Proc("")
        if "ls-files" in cmd:
            return _Proc("pipeline/run_pipeline.py\ndata/samples/leak.mp4\n")
        return _Proc("")

    monkeypatch.setattr(preflight.subprocess, "run", _fake_run)
    name, status, detail = preflight.check_git_status()
    assert name == "git_status"
    assert status == "FAIL"
    assert "leak.mp4" in detail


def test_gpu_warns_when_ort_on_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    """check_gpu returns WARN (not FAIL) when InsightFace runs on CPU."""
    import pipeline.faces as faces_mod

    monkeypatch.setattr(faces_mod, "get_face_app", lambda: None)
    monkeypatch.setattr(faces_mod, "get_active_provider", lambda: "CPUExecutionProvider")
    _, status, detail = preflight.check_gpu()
    assert status == "WARN"
    assert "faces run on CPU" in detail


def test_preflight_main_exit_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() returns 0 on PASS/WARN and 1 on any FAIL."""
    monkeypatch.setattr(
        preflight,
        "run_all_checks",
        lambda: [("a", "PASS", "ok"), ("b", "WARN", "cpu"), ("c", "INFO", "offline")],
    )
    assert preflight.main() == 0

    monkeypatch.setattr(
        preflight,
        "run_all_checks",
        lambda: [("a", "PASS", "ok"), ("b", "FAIL", "broken")],
    )
    assert preflight.main() == 1
