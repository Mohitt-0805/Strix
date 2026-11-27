"""Tests for scripts/run_eval.py evaluation harness."""

from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from pipeline.contract import Frame, Metrics, PipelineResult
from scripts.run_eval import (
    EvalCase,
    evaluate_best_frame,
    evaluate_link,
    evaluate_search_entries,
    load_manifest,
    run_evaluation,
)


def _make_frame(t: float, rel: str = "Medium", ready: bool = True) -> Frame:
    return Frame(
        frame_id=f"f_{int(t * 1000):06d}",
        frame_path="f.jpg",
        timestamp_sec=t,
        quality_score=0.75,
        reliability=rel,  # type: ignore[arg-type]
        flags=[],
        enhanced=False,
        enhancement=None,
        metrics=Metrics(sharpness=0.8, face_size=0.8, pose_yaw=5.0, illumination=0.8, occlusion=0.0),
        embedding_path="e.npy",
        match_ready=ready,
        crop_path="c.jpg",
    )


def test_evaluate_link_and_best_frame_math() -> None:
    """Verify link_ok (person/none, with/without gt_intervals) and best_frame rank math."""
    res_person = PipelineResult(
        clip_id="c",
        transaction_time="2026-11-27T10:00:00",
        person_track_id=1,
        best_frames=[_make_frame(12.0), _make_frame(14.0), _make_frame(18.0)],
        link_confidence="High",
    )
    case_no_gt = EvalCase("c1", "c.mp4", "atm_40", 15.0, 5.0, "person", [], None, "yes", "")
    assert evaluate_link(res_person, case_no_gt) is True

    case_gt_pass = EvalCase("c2", "c.mp4", "atm_40", 15.0, 5.0, "person", [(10.0, 15.0)], None, "yes", "")
    assert evaluate_link(res_person, case_gt_pass) is True  # 2/3 >= 0.5

    case_gt_fail = EvalCase("c3", "c.mp4", "atm_40", 15.0, 5.0, "person", [(17.0, 19.0)], None, "yes", "")
    assert evaluate_link(res_person, case_gt_fail) is False  # 1/3 < 0.5

    res_none = PipelineResult(clip_id="c", transaction_time="t", person_track_id=None, best_frames=[])
    case_none = EvalCase("c4", "c.mp4", "atm_40", 15.0, 5.0, "none", [], None, "unknown", "")
    assert evaluate_link(res_none, case_none) is True
    assert evaluate_link(res_person, case_none) is False

    bf = evaluate_best_frame([_make_frame(10.0), _make_frame(14.2), _make_frame(16.0)], manual_best_t=14.0)
    assert bf["abs_diff"] == pytest.approx(4.0)
    assert bf["within_1_5s"] is False
    assert bf["nearest_rank"] == 2


def test_run_evaluation_stubbed_handles_exception_and_writes_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Exception in one case becomes an ERROR/FAIL row without stopping; report & CSV are written."""
    from scripts import run_eval

    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "case_id,clip,atm_id,tx_sec,window_sec,expect_link,gt_intervals,manual_best_t,expect_frontal,notes\n"
        "ok_case,clip1.mp4,atm_40,10,5,person,,10.2,yes,note1\n"
        "boom_case,clip2.mp4,atm_40,20,5,person,,,no,note2\n"
        "none_case,clip3.mp4,atm_40,30,5,none,,,unknown,note3\n",
        encoding="utf-8",
    )

    def _stub_run(clip_path: str | Path, **_kwargs: object) -> PipelineResult:
        name = Path(clip_path).name
        if name == "clip2.mp4":
            raise RuntimeError("corrupt stream")
        if name == "clip3.mp4":
            return PipelineResult(clip_id="clip3", transaction_time="t", person_track_id=None, best_frames=[], link_confidence="Low")
        return PipelineResult(
            clip_id="clip1",
            transaction_time="t",
            person_track_id=1,
            best_frames=[_make_frame(10.0, rel="High", ready=True)],
            link_confidence="High",
            timings_ms={"frames": 500.0},
        )

    monkeypatch.setattr(run_eval, "get_run", lambda: _stub_run)
    out_md = tmp_path / "eval_report.md"
    rows, _ = run_evaluation(manifest, out_path=out_md)

    assert len(rows) == 3
    assert rows[0]["status"] == "OK" and rows[0]["link_ok"] is True and rows[0]["within_1_5s"] is True
    assert rows[1]["status"] == "ERROR" and "corrupt stream" in rows[1]["error"]
    assert rows[2]["status"] == "OK" and rows[2]["link_ok"] is True
    assert out_md.exists()
    assert (tmp_path / "eval_cases.csv").exists()
    text = out_md.read_text(encoding="utf-8")
    assert "boom_case" in text and "corrupt stream" in text


def test_malformed_manifest_raises_and_exits_2(tmp_path: Path) -> None:
    """Malformed manifest raises ValueError and exits with code 2 from CLI."""
    bad = tmp_path / "bad.csv"
    bad.write_text("case_id,clip\nc1,a.mp4\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        load_manifest(bad)

    bad_val = tmp_path / "bad_val.csv"
    bad_val.write_text(
        "case_id,clip,atm_id,tx_sec,window_sec,expect_link,gt_intervals,manual_best_t,expect_frontal,notes\n"
        "c1,a.mp4,atm_40,10,5,invalid_val,,,yes,\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, "scripts/run_eval.py", "--manifest", str(bad_val)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2


def test_evaluate_search_entries_synthetic() -> None:
    """Synthetic search evaluation checks both other_clips and same_clip_diff_track."""
    va = np.zeros(512, dtype=np.float32)
    va[0] = 1.0
    vb = np.zeros(512, dtype=np.float32)
    vb[1] = 1.0

    entries = [
        {"clip": "c1.mp4", "track_id": 1, "t": 1.0, "match_ready": True, "person_label": "A", "embedding": va},
        {"clip": "c1.mp4", "track_id": 2, "t": 5.0, "match_ready": True, "person_label": "A", "embedding": va},
        {"clip": "c2.mp4", "track_id": 1, "t": 2.0, "match_ready": True, "person_label": "A", "embedding": va},
        {"clip": "c1.mp4", "track_id": 3, "t": 9.0, "match_ready": True, "person_label": "B", "embedding": vb},
        {"clip": "c2.mp4", "track_id": 2, "t": 8.0, "match_ready": True, "person_label": "B", "embedding": vb},
    ]
    res = evaluate_search_entries(entries)
    assert res["other_clips"]["n"] == 5
    assert res["other_clips"]["top1_acc"] == pytest.approx(1.0)
    assert res["other_clips"]["small_sample"] is True
    assert res["same_clip_diff_track"]["n"] == 5
    assert res["same_clip_diff_track"]["top1_acc"] == pytest.approx(2.0 / 5.0)
