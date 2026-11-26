"""Unit tests for pipeline/link_transaction.py using hand-built Track objects."""

import subprocess
import sys

import pytest

from pipeline.detect_track import Track
from pipeline.link_transaction import compute_anchor, link_transaction, load_zone


# Zone covers x in [0.5, 1.0], y in [0.2, 1.0] on a 200x200 frame (x: 100..200, y: 40..200).
TEST_ZONE = [[0.5, 0.2], [1.0, 0.2], [1.0, 1.0], [0.5, 1.0]]
FRAME_W, FRAME_H = 200, 200


def _make_track(track_id: int, times: list[float], box: list[float]) -> Track:
    return Track(
        track_id=track_id,
        observations=[{"t": t, "box": list(box), "score": 0.9} for t in times],
    )


def test_import_link_transaction_does_not_import_heavy_libs() -> None:
    """Importing pipeline.link_transaction must not import cv2 or numpy eagerly."""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, pipeline.link_transaction; "
                "assert not {'cv2', 'numpy', 'torch'}.intersection(sys.modules)"
            ),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_load_zone_and_missing_raises() -> None:
    """load_zone returns polygon for existing ATM and raises KeyError when missing."""
    zone = load_zone("atm_01")
    assert "polygon" in zone
    with pytest.raises(KeyError):
        load_zone("nonexistent_atm_99")


def test_single_person_in_zone() -> None:
    """Single person standing in the ATM zone is chosen."""
    tr = _make_track(1, [8.0, 8.5, 9.0, 9.5, 10.0], [120.0, 60.0, 180.0, 180.0])
    res = link_transaction([tr], TEST_ZONE, FRAME_W, FRAME_H, tx_offset_sec=10.0, window_sec=5.0)
    assert res.chosen_track_id == 1
    assert res.fallback is False
    assert res.low_margin is False
    assert res.ranking[0]["dwell_sec_in_zone"] >= 2.0


def test_two_people_one_in_zone_one_queueing_outside() -> None:
    """Person inside the zone beats person queueing outside."""
    in_zone = _make_track(1, [8.0, 8.5, 9.0, 9.5, 10.0], [120.0, 60.0, 180.0, 180.0])
    outside = _make_track(2, [7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0], [10.0, 60.0, 70.0, 180.0])

    res = link_transaction(
        [outside, in_zone], TEST_ZONE, FRAME_W, FRAME_H, tx_offset_sec=9.0, window_sec=5.0
    )
    assert res.chosen_track_id == 1
    assert res.ranking[0]["track_id"] == 1
    assert res.ranking[1]["dwell_sec_in_zone"] == 0.0


def test_nobody_in_zone_returns_none() -> None:
    """If best dwell_sec < 1.0 s, chosen_track_id is None with exact reason."""
    outside = _make_track(1, [8.0, 8.5, 9.0, 9.5], [10.0, 60.0, 70.0, 180.0])
    res = link_transaction([outside], TEST_ZONE, FRAME_W, FRAME_H, tx_offset_sec=9.0, window_sec=5.0)
    assert res.chosen_track_id is None
    assert res.reason == "No person was in the ATM zone in this window"


def test_two_people_similar_dwell_sets_low_margin() -> None:
    """Two people in the zone for similar time triggers low_margin=True."""
    tr1 = _make_track(1, [8.0, 8.5, 9.0, 9.5, 10.0], [120.0, 60.0, 180.0, 180.0])
    tr2 = _make_track(2, [10.5, 11.0, 11.5, 12.0], [120.0, 60.0, 180.0, 180.0])
    res = link_transaction(
        [tr1, tr2], TEST_ZONE, FRAME_W, FRAME_H, tx_offset_sec=10.0, window_sec=5.0
    )
    assert res.chosen_track_id == 1
    assert res.low_margin is True
    assert "low margin" in res.reason.lower()


def test_track_outside_window_is_ignored() -> None:
    """A track completely outside [tx - window, tx + window] is ignored."""
    far_track = _make_track(1, [40.0, 40.5, 41.0, 41.5, 42.0], [120.0, 60.0, 180.0, 180.0])
    res = link_transaction(
        [far_track], TEST_ZONE, FRAME_W, FRAME_H, tx_offset_sec=10.0, window_sec=5.0
    )
    assert res.chosen_track_id is None
    assert res.ranking == []


def test_fallback_when_no_zone() -> None:
    """When zone is None, fallback selects longest track nearest frame centre."""
    edge_short = _make_track(1, [9.0, 9.5], [0.0, 0.0, 40.0, 80.0])
    center_long = _make_track(2, [8.0, 8.5, 9.0, 9.5, 10.0], [70.0, 50.0, 130.0, 150.0])
    res = link_transaction(
        [edge_short, center_long], None, FRAME_W, FRAME_H, tx_offset_sec=9.0, window_sec=5.0
    )
    assert res.fallback is True
    assert res.chosen_track_id == 2
    assert "warning" in res.reason.lower()


def test_tall_box_with_feet_in_small_floor_polygon_counts() -> None:
    """(a) Tall box whose bottom-centre is in a small floor polygon counts even with small area overlap."""
    floor_zone = [[0.4, 0.85], [0.8, 0.85], [0.8, 0.95], [0.4, 0.95]]  # y: 170..190 on 200x200
    tall_person = _make_track(1, [8.0, 8.5, 9.0, 9.5, 10.0], [100.0, 20.0, 140.0, 180.0])

    res = link_transaction(
        [tall_person], floor_zone, FRAME_W, FRAME_H, tx_offset_sec=9.0, window_sec=5.0
    )
    assert res.chosen_track_id == 1
    assert res.ranking[0]["mean_zone_overlap"] < 0.2
    assert res.ranking[0]["anchor_in_zone_frac"] == 1.0
    assert res.ranking[0]["dwell_sec_in_zone"] == pytest.approx(2.5)


def test_tall_box_above_polygon_with_feet_outside_does_not_count() -> None:
    """(b) Tall box above the floor polygon with feet outside does not count."""
    floor_zone = [[0.4, 0.85], [0.8, 0.85], [0.8, 0.95], [0.4, 0.95]]  # y: 170..190
    above_person = _make_track(1, [8.0, 8.5, 9.0, 9.5, 10.0], [100.0, 20.0, 140.0, 160.0])

    res = link_transaction(
        [above_person], floor_zone, FRAME_W, FRAME_H, tx_offset_sec=9.0, window_sec=5.0
    )
    assert res.chosen_track_id is None
    assert res.ranking[0]["anchor_in_zone_frac"] == 0.0
    assert res.ranking[0]["dwell_sec_in_zone"] == 0.0


def test_cutoff_feet_at_bottom_edge_uses_85_percent_anchor() -> None:
    """(c) Box touching bottom edge (y2 >= 98% of frame_h) uses 85% height fallback anchor."""
    # y2=198 >= 0.98 * 200 (196) -> estimated anchor at y1 + 0.85*(198 - 50) = 175.8
    ax, ay, estimated = compute_anchor([100.0, 50.0, 140.0, 198.0], FRAME_H)
    assert estimated is True
    assert ax == pytest.approx(120.0)
    assert ay == pytest.approx(50.0 + 0.85 * 148.0)

    # Polygon covers y: 170..190 (excludes y2=198, includes estimated ay=175.8).
    floor_zone = [[0.4, 0.85], [0.8, 0.85], [0.8, 0.95], [0.4, 0.95]]
    cutoff_person = _make_track(1, [8.0, 8.5, 9.0, 9.5, 10.0], [100.0, 50.0, 140.0, 198.0])
    res = link_transaction(
        [cutoff_person], floor_zone, FRAME_W, FRAME_H, tx_offset_sec=9.0, window_sec=5.0
    )
    assert res.chosen_track_id == 1
    assert res.ranking[0]["anchor_in_zone_frac"] == 1.0


def test_confidence_high_medium_low() -> None:
    """Confidence tiers High, Medium, and Low follow pipeline/config/link.json thresholds."""
    in_box = [120.0, 60.0, 180.0, 180.0]
    out_box = [10.0, 60.0, 70.0, 180.0]

    # High: window_len=10 (tx=10, window=5), dwell=5.0s (dwell_frac=0.5 >= 0.4), anchor_frac=1.0 >= 0.5
    high_tr = _make_track(1, [t * 0.5 for t in range(10, 20)], in_box)
    res_high = link_transaction([high_tr], TEST_ZONE, FRAME_W, FRAME_H, tx_offset_sec=10.0, window_sec=5.0)
    assert res_high.confidence == "High"
    assert "Confidence High:" in res_high.reason

    # Medium: dwell=2.0s of 10.0s (dwell_frac=0.20 >= 0.15, < 0.4)
    med_tr = _make_track(1, [8.0, 8.5, 9.0, 9.5], in_box)
    res_med = link_transaction([med_tr], TEST_ZONE, FRAME_W, FRAME_H, tx_offset_sec=10.0, window_sec=5.0)
    assert res_med.confidence == "Medium"
    assert "Confidence Medium:" in res_med.reason

    # Low: dwell=1.5s of 20.0s (dwell_frac=0.075 < 0.15) and anchor_frac=3/12=0.25 < 0.3
    low_times = [float(t) for t in range(1, 13)]
    low_tr = Track(
        track_id=1,
        observations=[
            {"t": t, "box": in_box if t <= 2.0 else out_box, "score": 0.9}
            for t in low_times
        ],
    )
    res_low = link_transaction([low_tr], TEST_ZONE, FRAME_W, FRAME_H, tx_offset_sec=10.0, window_sec=10.0)
    assert res_low.chosen_track_id == 1
    assert res_low.confidence == "Low"
    assert "Confidence Low:" in res_low.reason


def test_many_tracks_warning() -> None:
    """More than 3 tracks in the window sets track_count_in_window and adds warning."""
    in_box = [120.0, 60.0, 180.0, 180.0]
    out_box = [10.0, 60.0, 70.0, 180.0]
    tracks = [
        _make_track(1, [8.0, 8.5, 9.0, 9.5, 10.0], in_box),
        _make_track(2, [8.0, 8.5], out_box),
        _make_track(3, [9.0, 9.5], out_box),
        _make_track(4, [10.0, 10.5], out_box),
    ]
    res = link_transaction(tracks, TEST_ZONE, FRAME_W, FRAME_H, tx_offset_sec=10.0, window_sec=5.0)
    assert res.track_count_in_window == 4
    assert "many tracks, possible ID splits" in res.reason
