"""Tests for IoUTracker and ByteTrackAdapter using synthetic bounding boxes."""

import subprocess
import sys

from pipeline.detect_track import ByteTrackAdapter, IoUTracker


def test_import_detect_track_does_not_import_tracker_libs() -> None:
    """Importing pipeline.detect_track must not eagerly import supervision or scipy."""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, pipeline.detect_track; "
                "assert not {'torch', 'torchvision', 'cv2', 'supervision', 'scipy'}.intersection(sys.modules)"
            ),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_steady_moving_box_keeps_one_id() -> None:
    """(a) One box moving steadily across frames keeps a single track ID."""
    for tracker in (IoUTracker(), ByteTrackAdapter(frame_rate=2)):
        seen_ids: set[int] = set()
        for step in range(8):
            t = step * 0.5
            x = 100.0 + step * 12.0
            det = [{"box": [x, 50.0, x + 80.0, 250.0], "score": 0.9}]
            assignments = tracker.update(t, det)
            for tid, _ in assignments:
                seen_ids.add(tid)

        tracks = tracker.finish()
        assert len(seen_ids) == 1
        assert len(tracks) == 1
        assert len(tracks[0].observations) == 8
        assert tracks[0].first_t == 0.0
        assert tracks[0].last_t == 3.5
        assert tracks[0].duration == 3.5


def test_crossing_boxes_keep_two_ids() -> None:
    """(b) Two boxes crossing paths keep their two distinct track IDs."""
    tracker = IoUTracker(iou_thresh=0.3, max_gap_sec=2.0)

    # Box A moves left-to-right; Box B moves right-to-left at a different y-band
    # initially, then crosses horizontally while remaining separable by assignment.
    id_history_a: list[int] = []
    id_history_b: list[int] = []

    for step in range(9):
        t = step * 0.5
        ax = 50.0 + step * 25.0
        bx = 250.0 - step * 25.0
        det_a = {"box": [ax, 50.0, ax + 70.0, 210.0], "score": 0.9}
        det_b = {"box": [bx, 110.0, bx + 70.0, 270.0], "score": 0.9}
        assignments = tracker.update(t, [det_a, det_b])
        # Map assigned boxes back to det_a and det_b by y-coordinate (distinct even at x crossing).
        for tid, assigned_det in assignments:
            if abs(assigned_det["box"][1] - 50.0) < 1e-6:
                id_history_a.append(tid)
            else:
                id_history_b.append(tid)

    tracks = tracker.finish()
    assert len(tracks) == 2
    assert len(set(id_history_a)) == 1
    assert len(set(id_history_b)) == 1
    assert id_history_a[0] != id_history_b[0]


def test_gap_handling_1s_keeps_id_and_5s_starts_new_id() -> None:
    """(c) A 1.0 s gap keeps the same track ID; a 5.0 s gap starts a new track ID."""
    tracker = IoUTracker(iou_thresh=0.3, max_gap_sec=2.0)
    box = [{"box": [100.0, 100.0, 180.0, 260.0], "score": 0.9}]

    tid_0 = tracker.update(0.0, box)[0][0]
    # 1.0 s gap (t=1.0 <= max_gap_sec=2.0) -> keeps same ID.
    tid_1 = tracker.update(1.0, box)[0][0]
    assert tid_1 == tid_0

    # 5.0 s gap (t=6.0, gap=5.0 > max_gap_sec=2.0) -> expires old track, starts new ID.
    tid_2 = tracker.update(6.0, box)[0][0]
    assert tid_2 != tid_0

    tracks = tracker.finish()
    assert len(tracks) == 2
    assert tracks[0].first_t == 0.0
    assert tracks[0].last_t == 1.0
    assert tracks[1].first_t == 6.0
    assert tracks[1].last_t == 6.0
