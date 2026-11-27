"""Tests for pipeline.compare, fake_pipeline.search_with_enhancement, and adapter.get_search."""

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from pipeline.contract import SearchResult


def test_lazy_imports_compare() -> None:
    """Importing pipeline.compare and pipeline.adapter must not load heavy libs."""
    code = (
        "import sys; "
        "import pipeline.compare; "
        "import pipeline.adapter; "
        "loaded = [m for m in ('torch', 'cv2', 'insightface', 'onnxruntime') if m in sys.modules]; "
        "assert not loaded, f'Unexpected heavy imports: {loaded}'"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr or res.stdout


def test_adapter_get_search(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_search() switches between fake_pipeline and compare."""
    from pipeline import adapter, compare, fake_pipeline

    monkeypatch.setenv("USE_FAKE_PIPELINE", "1")
    assert adapter.get_search() is fake_pipeline.search_with_enhancement

    monkeypatch.setenv("USE_FAKE_PIPELINE", "0")
    assert adapter.get_search() is compare.search_with_enhancement


def _write_dummy_index(idx_dir: Path) -> None:
    v1 = np.zeros(512, dtype=np.float32)
    v1[0] = 1.0
    v2 = np.zeros(512, dtype=np.float32)
    v2[1] = 1.0
    meta = [
        {"track_id": 1, "t": 10.0, "crop_path": "c1.jpg", "reliability": "High", "match_ready": True},
        {"track_id": 2, "t": 20.0, "crop_path": "c2.jpg", "reliability": "Medium", "match_ready": True},
    ]
    np.savez(
        idx_dir / "index.npz",
        embeddings=np.vstack([v1, v2]).astype(np.float32),
        metadata_json=np.array(json.dumps(meta)),
    )


def test_disagreement_warning_boundary_016_vs_014(tmp_path: Path) -> None:
    """Warning triggers at delta=0.16 (> 0.15) and not at delta=0.14 (<= 0.15)."""
    from pipeline.compare import search_with_enhancement

    idx_dir = tmp_path / "idx"
    idx_dir.mkdir()
    _write_dummy_index(idx_dir)

    orig = np.zeros(512, dtype=np.float32)
    orig[0] = 1.0

    # Enh1 has similarity 0.84 with v1 -> delta = 0.16 > 0.15 -> warning.
    enh_warn = np.zeros(512, dtype=np.float32)
    enh_warn[0] = 0.84
    enh_warn[2] = float(np.sqrt(1.0 - 0.84**2))

    res_warn = search_with_enhancement(
        idx_dir,
        original_crop_path=None,
        original_embedding=orig,
        enhanced_embedding=enh_warn,
    )
    assert res_warn.basis == "original"
    assert res_warn.banner == "Possible leads only. A person must verify."
    assert res_warn.top_level_warning == "Enhancement changed the result. Treat with caution."
    assert res_warn.matches[0].warning == "Enhancement changed the result. Treat with caution."
    assert res_warn.matches[0].delta == pytest.approx(0.16, abs=1e-4)

    # Enh2 has similarity 0.86 with v1 -> delta = 0.14 <= 0.15 -> no warning.
    enh_ok = np.zeros(512, dtype=np.float32)
    enh_ok[0] = 0.86
    enh_ok[2] = float(np.sqrt(1.0 - 0.86**2))

    res_ok = search_with_enhancement(
        idx_dir,
        original_crop_path=None,
        original_embedding=orig,
        enhanced_embedding=enh_ok,
    )
    assert res_ok.top_level_warning is None
    assert res_ok.matches[0].warning is None
    assert res_ok.matches[0].delta == pytest.approx(0.14, abs=1e-4)


def test_enhanced_basis_fallback_and_empty_result_and_fake_parity(tmp_path: Path) -> None:
    """Basis switches to enhanced only when original is None; empty returns reason; fake matches model."""
    from pipeline import fake_pipeline
    from pipeline.compare import search_with_enhancement

    idx_dir = tmp_path / "idx"
    idx_dir.mkdir()
    _write_dummy_index(idx_dir)

    enh = np.zeros(512, dtype=np.float32)
    enh[0] = 1.0

    res_enh = search_with_enhancement(
        idx_dir,
        original_crop_path=None,
        original_embedding=None,
        enhanced_embedding=enh,
    )
    assert isinstance(res_enh, SearchResult)
    assert res_enh.basis == "enhanced"
    assert res_enh.reliability_note == "based on ENHANCED image, low reliability"
    assert res_enh.banner == "Possible leads only. A person must verify."

    res_empty = search_with_enhancement(
        idx_dir,
        original_crop_path=None,
        original_embedding=None,
        enhanced_embedding=None,
    )
    assert res_empty.basis == "none"
    assert res_empty.matches == []
    assert res_empty.reason is not None and len(res_empty.reason) > 0
    assert res_empty.banner == "Possible leads only. A person must verify."

    res_fake = fake_pipeline.search_with_enhancement(idx_dir, "orig.jpg", "enh.jpg")
    assert isinstance(res_fake, SearchResult)
    assert res_fake.basis == "original"
    assert res_fake.banner == "Possible leads only. A person must verify."


def test_leave_one_out_and_wrong_match_synthetic() -> None:
    """Synthetic-embedding tests for evaluate_leave_one_out (settings 1 & 2) and wrong-match."""
    from scripts.enhancement_eval import evaluate_leave_one_out

    v1 = np.zeros(512, dtype=np.float32)
    v1[0] = 1.0
    v1_other = np.zeros(512, dtype=np.float32)
    v1_other[0] = 0.9
    v1_other[1] = float(np.sqrt(1.0 - 0.9**2))
    v2 = np.zeros(512, dtype=np.float32)
    v2[2] = 1.0

    embs = np.vstack([v1, v1_other, v2]).astype(np.float32)
    meta = [
        {"track_id": 1, "t": 10.0, "crop_path": "a.jpg"},
        {"track_id": 1, "t": 12.0, "crop_path": "b.jpg"},
        {"track_id": 2, "t": 20.0, "crop_path": "c.jpg"},
    ]

    # Query matches own row at t=10.0 -> own row removed, best remaining is track 1 (sim 0.90), best other is track 2 (0.0).
    loo = evaluate_leave_one_out(v1, query_track_id=1, query_t=10.0, index_embeddings=embs, index_metadata=meta)
    assert loo["top1_correct"] is True
    assert loo["best_same"] == pytest.approx(0.9, abs=1e-4)
    assert loo["best_other"] == pytest.approx(0.0, abs=1e-4)
    assert loo["margin"] == pytest.approx(0.9, abs=1e-4)

    # Distractor query aligned with v1 but belonging to track 2 (1 row -> top1_correct is None/"n/a") -> best_other_meta is track 1.
    loo_dist = evaluate_leave_one_out(v1, query_track_id=2, query_t=20.0, index_embeddings=embs, index_metadata=meta)
    assert loo_dist["top1_correct"] is None
    assert int(loo_dist["best_other_meta"]["track_id"]) == 1


def test_identity_grouping_and_na_handling() -> None:
    """Identity mapping groups multiple tracks and returns n/a (< 2 remaining rows)."""
    from scripts.enhancement_eval import evaluate_leave_one_out

    v1 = np.zeros(512, dtype=np.float32)
    v1[0] = 1.0
    v_same_person = np.zeros(512, dtype=np.float32)
    v_same_person[0] = 0.85
    v_same_person[1] = float(np.sqrt(1.0 - 0.85**2))
    v_other = np.zeros(512, dtype=np.float32)
    v_other[2] = 1.0

    embs = np.vstack([v1, v_same_person, v_same_person, v_other]).astype(np.float32)
    meta = [
        {"track_id": 1, "t": 10.0},
        {"track_id": 2, "t": 20.0},
        {"track_id": 2, "t": 22.0},
        {"track_id": 3, "t": 30.0},
    ]

    # Tracks 1 and 2 belong to "person_A" -> 2 remaining rows for person_A -> valid top1_correct.
    identities = {1: "person_A", 2: "person_A", 3: "person_B"}
    loo_grouped = evaluate_leave_one_out(v1, 1, 10.0, embs, meta, identities=identities)
    assert loo_grouped["insufficient_same_rows"] is False
    assert loo_grouped["top1_correct"] is True
    assert loo_grouped["best_same"] == pytest.approx(0.85, abs=1e-4)

    # Track 3 has 0 remaining rows for person_B (< 2) -> insufficient_same_rows=True (n/a).
    loo_single = evaluate_leave_one_out(v_other, 3, 30.0, embs, meta, identities=identities)
    assert loo_single["insufficient_same_rows"] is True
    assert loo_single["top1_correct"] is None
    assert loo_single["best_same"] is None


