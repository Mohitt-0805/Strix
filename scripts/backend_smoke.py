"""Backend readiness smoke test simulating a web backend using stdlib only."""

import argparse
import os
from pathlib import Path
import queue
import resource
import sys
import threading
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.adapter import get_index_clip, get_run, get_search
from pipeline.contract import IndexResult, PipelineResult, SearchResult
from pipeline.errors import (
    InvalidArgumentError,
    PipelineError,
    VideoNotFoundError,
    ZoneNotFoundError,
)


def _peak_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def _is_fake() -> bool:
    return os.environ.get("USE_FAKE_PIPELINE", "").strip().lower() in {"1", "true", "yes", "on"}


def run_smoke(
    video_path: Path,
    atm_id: str,
    tx_sec: float,
    window_sec: float,
    out_dir: Path,
) -> list[tuple[str, bool, str]]:
    """Run all backend readiness checks and return list of (check_name, passed, detail)."""
    checks: list[tuple[str, bool, str]] = []
    fake_mode = _is_fake()
    run_fn = get_run()
    index_fn = get_index_clip()
    search_fn = get_search()

    # 1. Worker thread + Queue progress callback.
    ev_q: queue.Queue[dict[str, Any] | None] = queue.Queue()
    worker_out: dict[str, Any] = {}

    def _worker() -> None:
        try:
            worker_out["res"] = run_fn(
                clip_path=video_path,
                tx_offset_sec=tx_sec,
                window_sec=window_sec,
                atm_id=atm_id,
                out_dir=out_dir,
                progress_cb=ev_q.put,
            )
        except Exception as exc:
            worker_out["err"] = exc
        finally:
            ev_q.put(None)

    t_w0 = time.perf_counter()
    th = threading.Thread(target=_worker, daemon=True)
    th.start()

    events: list[dict[str, Any]] = []
    while True:
        item = ev_q.get()
        if item is None:
            break
        events.append(item)
        print(f"[worker] {item['fraction']:.2f} | {item['stage']:<14} | {item['message']}")
    th.join()
    t_run1 = time.perf_counter() - t_w0

    if "err" in worker_out:
        checks.append(("worker_progress", False, f"Worker raised: {worker_out['err']}"))
        return checks

    res: PipelineResult = worker_out["res"]
    fracs = [float(e["fraction"]) for e in events]
    monotonic = fracs == sorted(fracs)
    last_ok = bool(events and events[-1]["stage"] == "done" and abs(float(events[-1]["fraction"]) - 1.0) < 1e-6)
    checks.append(("worker_progress", monotonic and last_ok, f"events={len(events)}, monotonic={monotonic}, last_done={last_ok}"))
    print(f"[mem] after worker_progress: {_peak_mb():.1f} MB")

    # 2. Serialisation round-trip (PipelineResult, IndexResult, SearchResult).
    try:
        res_rt = PipelineResult.model_validate_json(res.model_dump_json())
        idx_res = index_fn(clip_path=video_path, start_sec=0.0, end_sec=min(30.0, max(10.0, tx_sec)), out_dir=out_dir)
        idx_rt = IndexResult.model_validate_json(idx_res.model_dump_json())
        orig_crop = res.best_frames[0].crop_path if res.best_frames else None
        orig_emb = None
        if not fake_mode and res.best_frames:
            from pipeline.embeddings import load_embedding

            orig_emb = load_embedding(res.best_frames[0].embedding_path)
        s_res = search_fn(
            index_dir=Path(idx_res.index_json_path).parent,
            original_crop_path=orig_crop,
            original_embedding=orig_emb,
        )
        s_rt = SearchResult.model_validate_json(s_res.model_dump_json())
        ser_ok = (res_rt.clip_id == res.clip_id) and (idx_rt.clip_id == idx_res.clip_id) and (s_rt.banner == s_res.banner)
        checks.append(("serialisation", ser_ok, "PipelineResult, IndexResult, SearchResult round-tripped"))
    except Exception as exc:
        checks.append(("serialisation", False, f"{type(exc).__name__}: {exc}"))
    print(f"[mem] after serialisation: {_peak_mb():.1f} MB")

    # 3. Paths inside out_dir & existing.
    base_resolved = out_dir.resolve()
    print(f"Static files base directory: {out_dir} ({base_resolved})")
    if fake_mode:
        paths_ok = all(bool(fr.frame_path and fr.embedding_path) for fr in res.best_frames)
        checks.append(("paths", paths_ok, "fake mode paths present"))
    else:
        bad_paths: list[str] = []
        for fr in res.best_frames:
            for p_str in (fr.frame_path, fr.crop_path, fr.embedding_path):
                if not p_str:
                    continue
                p = Path(p_str)
                if not p.exists():
                    bad_paths.append(f"missing:{p}")
                elif not p.resolve().is_relative_to(base_resolved):
                    bad_paths.append(f"outside_out_dir:{p}")
            if fr.enhancement is not None:
                ep = Path(fr.enhancement.enhanced_path)
                if not ep.exists() or not ep.resolve().is_relative_to(base_resolved):
                    bad_paths.append(f"bad_enh:{ep}")
        checks.append(("paths", len(bad_paths) == 0, "all paths exist inside out_dir" if not bad_paths else ", ".join(bad_paths)))
    print(f"[mem] after paths: {_peak_mb():.1f} MB")

    # 4. Typed errors & non-errors.
    err_failures: list[str] = []
    expected_cases: list[tuple[str, dict[str, Any], type[PipelineError]]] = [
        ("window_0", {"clip_path": video_path, "tx_offset_sec": tx_sec, "window_sec": 0.0}, InvalidArgumentError),
        ("bad_poly", {"clip_path": video_path, "tx_offset_sec": tx_sec, "zone_polygon_norm": [[0.1, 0.1], [0.9, 0.9]]}, InvalidArgumentError),
        ("unknown_atm", {"clip_path": video_path, "tx_offset_sec": tx_sec, "atm_id": "unknown_atm_999"}, ZoneNotFoundError),
    ]
    if not fake_mode:
        expected_cases.extend(
            [
                ("missing_file", {"clip_path": out_dir / "nope_missing.mp4", "tx_offset_sec": 5.0}, VideoNotFoundError),
                ("tx_outside", {"clip_path": video_path, "tx_offset_sec": 999999.0}, InvalidArgumentError),
            ]
        )

    for label, kw, exc_cls in expected_cases:
        try:
            run_fn(**kw)
            err_failures.append(f"{label}:did_not_raise")
        except exc_cls as exc:
            if not getattr(exc, "code", None):
                err_failures.append(f"{label}:missing_code")
        except Exception as exc:
            err_failures.append(f"{label}:wrong_exc({type(exc).__name__})")

    if not fake_mode:
        # "no person" at tx=120 must NOT raise.
        try:
            no_p = run_fn(clip_path=video_path, tx_offset_sec=120.0, window_sec=8.0, atm_id=atm_id, out_dir=out_dir)
            if no_p.best_frames:
                err_failures.append("no_person:expected_empty_best_frames")
        except Exception as exc:
            err_failures.append(f"no_person:raised({type(exc).__name__})")

    checks.append(("errors_and_non_errors", len(err_failures) == 0, "all expected errors + non-errors OK" if not err_failures else ", ".join(err_failures)))
    print(f"[mem] after errors: {_peak_mb():.1f} MB")

    # 5. Repeated sequential & concurrent use.
    try:
        t_s0 = time.perf_counter()
        res_seq_b = run_fn(clip_path=video_path, tx_offset_sec=120.0 if not fake_mode else 20.0, window_sec=6.0, atm_id=atm_id, out_dir=out_dir)
        t_seq_b = time.perf_counter() - t_s0
        no_overwrite = True
        if not fake_mode:
            no_overwrite = (out_dir / video_path.stem / f"tx{tx_sec:g}_w{window_sec:g}_{atm_id}" / "result.json").exists() and (
                out_dir / video_path.stem / f"tx120_w6_{atm_id}" / "result.json"
            ).exists()
        checks.append(("repeated_sequential", no_overwrite and res_seq_b is not None, f"t1={t_run1:.2f}s, t2={t_seq_b:.2f}s"))
    except Exception as exc:
        t_seq_b = 0.0
        checks.append(("repeated_sequential", False, f"{type(exc).__name__}: {exc}"))

    conc_results: dict[str, Any] = {}
    conc_times: dict[str, float] = {}
    conc_errs: dict[str, Exception] = {}

    def _conc_worker(name: str, tx_val: float) -> None:
        tc0 = time.perf_counter()
        try:
            conc_results[name] = run_fn(
                clip_path=video_path,
                tx_offset_sec=tx_val,
                window_sec=window_sec,
                atm_id=atm_id,
                out_dir=out_dir / f"conc_{name}",
            )
        except Exception as exc:
            conc_errs[name] = exc
        finally:
            conc_times[name] = time.perf_counter() - tc0

    t_c0 = time.perf_counter()
    ta = threading.Thread(target=_conc_worker, args=("A", tx_sec))
    tb = threading.Thread(target=_conc_worker, args=("B", 120.0 if not fake_mode else 20.0))
    ta.start()
    tb.start()
    ta.join()
    tb.join()
    t_conc_wall = time.perf_counter() - t_c0

    serial_est = t_run1 + t_seq_b
    conc_ok = len(conc_errs) == 0 and len(conc_results) == 2
    slower_than_serial = t_conc_wall > serial_est * 1.05
    if not conc_ok or slower_than_serial:
        print("Concurrency note: run one job at a time")
    conc_detail = (
        f"ok={conc_ok}, wall={t_conc_wall:.2f}s (A={conc_times.get('A', 0):.2f}s, B={conc_times.get('B', 0):.2f}s), "
        f"serial={serial_est:.2f}s, errs={list(conc_errs.values())}"
    )
    checks.append(("concurrent_two_threads", conc_ok, conc_detail))
    print(f"[mem] final peak RSS: {_peak_mb():.1f} MB")

    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Backend readiness smoke test for Strix.")
    parser.add_argument("--video", type=Path, default=Path("data/samples/sample2.mp4"))
    parser.add_argument("--atm-id", type=str, default="atm_155")
    parser.add_argument("--tx", type=float, default=155.0)
    parser.add_argument("--window", type=float, default=6.0)
    parser.add_argument("--out-dir", type=Path, default=Path("data/outputs/backend_smoke"))
    args = parser.parse_args()

    checks = run_smoke(args.video, args.atm_id, args.tx, args.window, args.out_dir)

    print(f"\n{'Check':<24}  {'Status':<6}  {'Detail'}")
    print("-" * 86)
    any_fail = False
    for name, ok, detail in checks:
        status = "PASS" if ok else "FAIL"
        if not ok:
            any_fail = True
        print(f"{name:<24}  {status:<6}  {detail}")

    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
