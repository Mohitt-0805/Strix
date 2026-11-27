"""Fast backend smoke test running against USE_FAKE_PIPELINE=1 (no ML models)."""

from pathlib import Path
import pytest

from scripts.backend_smoke import run_smoke


def test_backend_smoke_fake_pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """All backend smoke checks pass against fake_pipeline without loading ML libraries."""
    monkeypatch.setenv("USE_FAKE_PIPELINE", "1")
    monkeypatch.delenv("DEMO_PACK_DIR", raising=False)

    checks = run_smoke(
        video_path=Path("data/samples/fake_clip.mp4"),
        atm_id="atm_40",
        tx_sec=15.0,
        window_sec=5.0,
        out_dir=tmp_path,
    )
    assert len(checks) >= 6
    for name, ok, detail in checks:
        assert ok, f"Check {name} failed: {detail}"
