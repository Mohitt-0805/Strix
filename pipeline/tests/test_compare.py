"""Tests for pipeline.compare, fake_pipeline.search_with_enhancement, and adapter.get_search."""

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from pipeline.contract import SearchResult


def test_lazy_imports_compare() -> None:
    """Importing pipeline.compare, fake_pipeline, and adapter must not load heavy libs."""
    code = (
        "import sys; "
        "import pipeline.compare; "
        "import pipeline.fake_pipeline; "
        "import pipeline.adapter; "
        "loaded = [m for m in ('torch', 'cv2', 'insightface', 'onnxruntime') if m in sys.modules]; "
        "assert not loaded, f'Unexpected heavy imports: {loaded}'"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr or res.stdout


def test_adapter_get_search_and_secondary_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_search() and get_secondary_scores() switch between fake_pipeline and compare."""
    from pipeline import adapter, compare, fake_pipeline

    monkeypatch.setenv("USE_FAKE_PIPELINE", "1")
    assert adapter.get_search() is fake_pipeline.search_with_enhancement
    assert adapter.get_secondary_scores() is fake_pipeline.secondary_scores

    monkeypatch.setenv("USE_FAKE_PIPELINE", "0")
    assert adapter.get_search() is compare.search_with_enhancement
    assert adapter.get_secondary_scores() is compare.secondary_scores


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


def test_secondary_scores_boundary_no_embedding_and_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    """secondary_scores warns at delta 0.16 not 0.14, handles missing embedding, and checks shapes."""
    from pipeline import compare

    row0 = np.zeros(512, dtype=np.float32)
    row0[0] = 1.0
    row1 = np.zeros(512, dtype=np.float32)
    row1[1] = 1.0
    rows = np.vstack([row0, row1]).astype(np.float32)

    enh_vec = np.zeros(512, dtype=np.float32)
    enh_vec[0] = 0.84
    enh_vec[2] = float(np.sqrt(1.0 - 0.84**2))

    # Original scores: [1.0, 0.14] vs enhanced cosines: [0.84, 0.0] -> deltas [0.16 (>0.15), 0.14 (<=0.15)].
    monkeypatch.setattr(compare, "_embed_image_path", lambda _p: enh_vec)
    res = compare.secondary_scores("enh.jpg", rows, [1.0, 0.14])

    assert res["basis"] == "original"
    assert res["reliability_note"] is None
    assert res["enhanced_embedding_found"] is True
    assert res["note"] is None
    assert res["top_level_warning"] == compare.ENHANCEMENT_WARNING
    assert len(res["rows"]) == 2
    assert res["rows"][0]["similarity_secondary"] == pytest.approx(0.84, abs=1e-4)
    assert res["rows"][0]["delta"] == pytest.approx(0.16, abs=1e-4)
    assert res["rows"][0]["warning"] == compare.ENHANCEMENT_WARNING
    assert res["rows"][1]["similarity_secondary"] == pytest.approx(0.0, abs=1e-4)
    assert res["rows"][1]["delta"] == pytest.approx(0.14, abs=1e-4)
    assert res["rows"][1]["warning"] is None

    # All <= 0.14 -> no top-level warning.
    res_quiet = compare.secondary_scores("enh.jpg", rows, [0.98, 0.14])
    assert res_quiet["top_level_warning"] is None
    assert all(r["warning"] is None for r in res_quiet["rows"])

    # Missing enhanced embedding -> None similarities and descriptive note.
    monkeypatch.setattr(compare, "_embed_image_path", lambda _p: None)
    res_missing = compare.secondary_scores("missing.jpg", rows, [1.0, 0.14])
    assert res_missing["enhanced_embedding_found"] is False
    assert res_missing["note"] is not None and len(res_missing["note"]) > 0
    assert res_missing["top_level_warning"] is None
    assert all(r["similarity_secondary"] is None and r["delta"] is None and r["warning"] is None for r in res_missing["rows"])

    # Empty (0, 512) rows accepted; bad width or mismatched lengths raise ValueError.
    empty_res = compare.secondary_scores("missing.jpg", np.zeros((0, 512), dtype=np.float32), [])
    assert empty_res["rows"] == []
    with pytest.raises(ValueError):
        compare.secondary_scores("missing.jpg", np.zeros((2, 128), dtype=np.float32), [0.5, 0.5])
    with pytest.raises(ValueError):
        compare.secondary_scores("missing.jpg", rows, [0.5])


def test_determine_basis_rules_and_fake_real_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    """determine_basis covers all 3 rules and fake/real secondary_scores share exact output shape."""
    from pipeline import compare, fake_pipeline

    v = np.ones(512, dtype=np.float32) / np.sqrt(512.0)

    b_orig = compare.determine_basis(v, v)
    assert b_orig["basis"] == "original"
    assert b_orig["reliability_note"] is None

    b_enh = compare.determine_basis(None, v)
    assert b_enh["basis"] == "enhanced"
    assert b_enh["reliability_note"] == "based on ENHANCED image, low reliability"

    b_none = compare.determine_basis(None, None)
    assert b_none["basis"] == "none"
    assert b_none["reason"] is not None and len(b_none["reason"]) > 0

    assert fake_pipeline.determine_basis(None, v) == b_enh
    assert fake_pipeline.determine_basis(None, None) == b_none

    rows = np.eye(3, 512, dtype=np.float32)
    orig_scores = [0.85, 0.60, 0.25]
    monkeypatch.setattr(compare, "_embed_image_path", lambda _p: rows[0])

    real_out = compare.secondary_scores("enh.jpg", rows, orig_scores)
    fake_out = fake_pipeline.secondary_scores("enh.jpg", rows, orig_scores)
    assert set(fake_out.keys()) == set(real_out.keys())
    assert len(fake_out["rows"]) == len(real_out["rows"]) == 3
    assert set(fake_out["rows"][0].keys()) == set(real_out["rows"][0].keys()) == {
        "similarity_secondary",
        "delta",
        "warning",
    }
    assert fake_pipeline.ENHANCEMENT_WARNING == compare.ENHANCEMENT_WARNING

    fake_none = fake_pipeline.secondary_scores(None, rows, orig_scores)
    assert fake_none["enhanced_embedding_found"] is False
    assert fake_none["note"] is not None
    assert all(r["similarity_secondary"] is None for r in fake_none["rows"])


