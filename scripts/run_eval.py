"""End-to-end evaluation harness for the Strix pipeline."""

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
import importlib.metadata as importlib_metadata
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.adapter import get_index_clip, get_run


MANIFEST_REQUIRED = {
    "case_id",
    "clip",
    "atm_id",
    "tx_sec",
    "window_sec",
    "expect_link",
    "gt_intervals",
    "manual_best_t",
    "expect_frontal",
    "notes",
}
PEOPLE_REQUIRED = {"clip", "t_start", "t_end", "person_label"}


@dataclass
class EvalCase:
    case_id: str
    clip: str
    atm_id: str
    tx_sec: float
    window_sec: float
    expect_link: str
    gt_intervals: list[tuple[float, float]]
    manual_best_t: float | None
    expect_frontal: str
    notes: str


@dataclass
class PersonInterval:
    clip: str
    t_start: float
    t_end: float
    person_label: str


def _parse_intervals(raw: str, row_num: int) -> list[tuple[float, float]]:
    text = raw.strip()
    if not text:
        return []
    out: list[tuple[float, float]] = []
    for part in text.split(";"):
        part = part.strip()
        if not part:
            continue
        if "-" not in part:
            raise ValueError(f"Manifest row {row_num}: invalid gt_intervals item {part!r} (expected start-end)")
        s_str, e_str = part.split("-", 1)
        try:
            s_val, e_val = float(s_str), float(e_str)
        except ValueError as exc:
            raise ValueError(f"Manifest row {row_num}: non-numeric gt_intervals {part!r}") from exc
        if e_val < s_val:
            raise ValueError(f"Manifest row {row_num}: gt_intervals end < start in {part!r}")
        out.append((s_val, e_val))
    return out


def load_manifest(path: Path) -> list[EvalCase]:
    """Load and validate manifest.csv, raising ValueError on malformed rows."""
    if not path.exists():
        raise ValueError(f"Manifest file not found: {path}")

    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"Manifest file is empty: {path}")
        missing = MANIFEST_REQUIRED - set(reader.fieldnames)
        if missing:
            raise ValueError(f"Manifest missing required columns: {sorted(missing)}")

        cases: list[EvalCase] = []
        seen_ids: set[str] = set()
        for row_num, row in enumerate(reader, start=2):
            cid = (row.get("case_id") or "").strip()
            clip = (row.get("clip") or "").strip()
            if not cid or not clip:
                raise ValueError(f"Manifest row {row_num}: case_id and clip must be non-empty")
            if cid in seen_ids:
                raise ValueError(f"Manifest row {row_num}: duplicate case_id {cid!r}")
            seen_ids.add(cid)

            try:
                tx_sec = float(row["tx_sec"])
                window_sec = float(row["window_sec"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Manifest row {row_num}: tx_sec and window_sec must be numbers") from exc
            if window_sec <= 0.0:
                raise ValueError(f"Manifest row {row_num}: window_sec must be > 0")

            expect_link = (row.get("expect_link") or "").strip().lower()
            if expect_link not in {"person", "none"}:
                raise ValueError(f"Manifest row {row_num}: expect_link must be 'person' or 'none', got {expect_link!r}")

            expect_frontal = (row.get("expect_frontal") or "").strip().lower()
            if expect_frontal not in {"yes", "no", "unknown"}:
                raise ValueError(
                    f"Manifest row {row_num}: expect_frontal must be yes|no|unknown, got {expect_frontal!r}"
                )

            manual_raw = (row.get("manual_best_t") or "").strip()
            manual_t: float | None = None
            if manual_raw:
                try:
                    manual_t = float(manual_raw)
                except ValueError as exc:
                    raise ValueError(f"Manifest row {row_num}: invalid manual_best_t {manual_raw!r}") from exc

            gt_intervals = _parse_intervals(row.get("gt_intervals") or "", row_num)
            cases.append(
                EvalCase(
                    case_id=cid,
                    clip=clip,
                    atm_id=(row.get("atm_id") or "").strip(),
                    tx_sec=tx_sec,
                    window_sec=window_sec,
                    expect_link=expect_link,
                    gt_intervals=gt_intervals,
                    manual_best_t=manual_t,
                    expect_frontal=expect_frontal,
                    notes=(row.get("notes") or "").strip(),
                )
            )
    if not cases:
        raise ValueError(f"Manifest contains 0 cases: {path}")
    return cases


def load_people(path: Path) -> list[PersonInterval]:
    """Load and validate people.csv, raising ValueError on malformed rows."""
    if not path.exists():
        raise ValueError(f"People file not found: {path}")

    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"People file is empty: {path}")
        missing = PEOPLE_REQUIRED - set(reader.fieldnames)
        if missing:
            raise ValueError(f"People CSV missing required columns: {sorted(missing)}")

        rows: list[PersonInterval] = []
        for row_num, row in enumerate(reader, start=2):
            clip = (row.get("clip") or "").strip()
            label = (row.get("person_label") or "").strip()
            if not clip or not label:
                raise ValueError(f"People row {row_num}: clip and person_label must be non-empty")
            try:
                t_start = float(row["t_start"])
                t_end = float(row["t_end"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"People row {row_num}: t_start and t_end must be numbers") from exc
            if t_end <= t_start:
                raise ValueError(f"People row {row_num}: t_end ({t_end}) must be > t_start ({t_start})")
            rows.append(PersonInterval(clip=clip, t_start=t_start, t_end=t_end, person_label=label))
    return rows


def evaluate_best_frame(best_frames: list[Any], manual_best_t: float | None) -> dict[str, Any]:
    """Compute abs(top1_t - manual_best_t), nearest rank within 1.0s, and within_1_5s."""
    if manual_best_t is None:
        return {"abs_diff": None, "nearest_rank": None, "within_1_5s": None}
    if not best_frames:
        return {"abs_diff": None, "nearest_rank": None, "within_1_5s": False}

    abs_diff = abs(float(best_frames[0].timestamp_sec) - float(manual_best_t))
    within_1_5s = abs_diff <= 1.5

    nearest_rank: int | None = None
    best_dt = 1.0 + 1e-9
    for idx, fr in enumerate(best_frames, start=1):
        dt = abs(float(fr.timestamp_sec) - float(manual_best_t))
        if dt <= best_dt:
            best_dt = dt
            nearest_rank = idx

    return {"abs_diff": round(abs_diff, 3), "nearest_rank": nearest_rank, "within_1_5s": within_1_5s}


def _in_intervals(t: float, intervals: list[tuple[float, float]]) -> bool:
    return any(s <= t <= e for s, e in intervals)


def evaluate_link(res: Any, case: EvalCase) -> bool:
    """Evaluate link_ok for expect_link=person|none and optional gt_intervals."""
    if case.expect_link == "none":
        return res.person_track_id is None
    if res.person_track_id is None:
        return False
    if not case.gt_intervals:
        return True
    if not res.best_frames:
        return False
    hits = sum(1 for fr in res.best_frames if _in_intervals(float(fr.timestamp_sec), case.gt_intervals))
    return (hits / len(res.best_frames)) >= 0.5


def evaluate_frontal(res: Any, expect_frontal: str) -> tuple[str, int, bool | None]:
    """Return (top1_reliability, match_ready_count, frontal_ok_or_None)."""
    top1_rel = res.best_frames[0].reliability if res.best_frames else "-"
    ready_cnt = sum(1 for fr in res.best_frames if fr.match_ready)
    if expect_frontal == "unknown":
        return top1_rel, ready_cnt, None
    expected = expect_frontal == "yes"
    return top1_rel, ready_cnt, (ready_cnt > 0) == expected


def _match_person_label(clip: str, t: float, people: list[PersonInterval]) -> str | None:
    clip_name = Path(clip).name
    for p in people:
        if (p.clip == clip or Path(p.clip).name == clip_name) and p.t_start <= t <= p.t_end:
            return p.person_label
    return None


def evaluate_search_entries(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Run leave-one-out search evaluation on labeled entries.

    Each entry: {'clip': str, 'track_id': int, 't': float, 'match_ready': bool,
                 'person_label': str | None, 'embedding': np.ndarray}.
    """
    import numpy as np

    queries = [e for e in entries if e.get("match_ready") and e.get("person_label")]
    results: dict[str, dict[str, Any]] = {}

    for setting in ("other_clips", "same_clip_diff_track"):
        n = 0
        top1_hits = 0
        top5_hits = 0
        correct_sims: list[float] = []
        wrong_sims: list[float] = []

        for qi, q in enumerate(queries):
            cands = []
            for ci, c in enumerate(entries):
                if ci == qi or not c.get("person_label"):
                    continue
                if setting == "other_clips" and c["clip"] == q["clip"]:
                    continue
                if setting == "same_clip_diff_track" and (c["clip"] != q["clip"] or c["track_id"] == q["track_id"]):
                    continue
                sim = float(np.dot(q["embedding"], c["embedding"]))
                cands.append((sim, c["person_label"] == q["person_label"]))

            if not cands:
                continue
            n += 1
            cands.sort(key=lambda x: x[0], reverse=True)
            top1_sim, top1_ok = cands[0]
            if top1_ok:
                top1_hits += 1
                correct_sims.append(top1_sim)
            else:
                wrong_sims.append(top1_sim)
            if any(ok for _, ok in cands[:5]):
                top5_hits += 1

        results[setting] = {
            "n": n,
            "top1_acc": (top1_hits / n) if n > 0 else None,
            "top5_acc": (top5_hits / n) if n > 0 else None,
            "mean_sim_correct": (sum(correct_sims) / len(correct_sims)) if correct_sims else None,
            "mean_sim_wrong": (sum(wrong_sims) / len(wrong_sims)) if wrong_sims else None,
            "small_sample": n < 10,
        }
    return results


def _git_commit_hash() -> str:
    try:
        proc = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True)
        return proc.stdout.strip()
    except Exception:
        return "unknown"


def _pkg_version(name: str) -> str:
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return "not installed"


def run_evaluation(
    manifest_path: Path,
    people_path: Path | None = None,
    out_path: Path = Path("docs/eval_report.md"),
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]] | None]:
    """Execute evaluation over manifest cases and optional people.csv search."""
    cases = load_manifest(manifest_path)
    people = load_people(people_path) if people_path is not None else []

    run_fn = get_run()
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for case in cases:
        t0 = time.perf_counter()
        try:
            res = run_fn(
                clip_path=case.clip,
                tx_offset_sec=case.tx_sec,
                window_sec=case.window_sec,
                atm_id=case.atm_id,
            )
            elapsed_s = round(time.perf_counter() - t0, 2)
            link_ok = evaluate_link(res, case)
            bf = evaluate_best_frame(res.best_frames, case.manual_best_t)
            top1_rel, ready_cnt, frontal_ok = evaluate_frontal(res, case.expect_frontal)

            all_flags: list[str] = []
            max_flag_scores: dict[str, float] = {}
            crop_paths: list[str] = []
            for fr in res.best_frames:
                for fl in fr.flags:
                    if fl not in all_flags:
                        all_flags.append(fl)
                if fr.flag_scores:
                    for fk, fv in fr.flag_scores.items():
                        max_flag_scores[fk] = max(max_flag_scores.get(fk, 0.0), float(fv))
                if fr.crop_path:
                    crop_paths.append(fr.crop_path)

            timings_s = {k: round(v / 1000.0, 2) for k, v in (res.timings_ms or {}).items()}
            row = {
                "case_id": case.case_id,
                "status": "OK",
                "error": "",
                "link_ok": link_ok,
                "link_confidence": res.link_confidence or "-",
                "top1_t": res.best_frames[0].timestamp_sec if res.best_frames else None,
                "best_diff_s": bf["abs_diff"],
                "best_rank": bf["nearest_rank"],
                "within_1_5s": bf["within_1_5s"],
                "top1_rel": top1_rel,
                "match_ready_cnt": ready_cnt,
                "frontal_ok": frontal_ok,
                "total_s": elapsed_s,
                "timings_s": timings_s,
                "flags": ", ".join(all_flags) if all_flags else "-",
                "max_flag_scores": json.dumps(max_flag_scores) if max_flag_scores else "-",
                "crop_paths": crop_paths,
                "reason": res.link_reason or res.selection_reason or "",
            }
            rows.append(row)
            if not link_ok or frontal_ok is False or bf["within_1_5s"] is False:
                failures.append(row)
        except Exception as exc:
            elapsed_s = round(time.perf_counter() - t0, 2)
            row = {
                "case_id": case.case_id,
                "status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
                "link_ok": False,
                "link_confidence": "-",
                "top1_t": None,
                "best_diff_s": None,
                "best_rank": None,
                "within_1_5s": False if case.manual_best_t is not None else None,
                "top1_rel": "-",
                "match_ready_cnt": 0,
                "frontal_ok": False if case.expect_frontal != "unknown" else None,
                "total_s": elapsed_s,
                "timings_s": {},
                "flags": "-",
                "max_flag_scores": "-",
                "crop_paths": [],
                "reason": f"{type(exc).__name__}: {exc}",
            }
            rows.append(row)
            failures.append(row)

    # Optional search evaluation when >= 2 distinct people are labelled.
    search_stats: dict[str, dict[str, Any]] | None = None
    distinct_people = {p.person_label for p in people}
    if people and len(distinct_people) >= 2:
        import numpy as np

        index_fn = get_index_clip()
        idx_cache: dict[str, Any] = {}
        entries: list[dict[str, Any]] = []
        for clip_str in sorted({c.clip for c in cases}):
            if not Path(clip_str).exists():
                continue
            idx_res = idx_cache.setdefault(clip_str, index_fn(clip_path=clip_str))
            npz = np.load(idx_res.index_npz_path)
            embs = np.asarray(npz["embeddings"], dtype=np.float32)
            raw_meta = npz["metadata_json"].item()
            meta = json.loads(raw_meta.decode("utf-8") if isinstance(raw_meta, bytes) else str(raw_meta))
            for emb, m in zip(embs, meta):
                entries.append(
                    {
                        "clip": clip_str,
                        "track_id": int(m["track_id"]),
                        "t": float(m["t"]),
                        "match_ready": bool(m.get("match_ready", False)),
                        "person_label": _match_person_label(clip_str, float(m["t"]), people),
                        "embedding": emb,
                    }
                )
        if entries:
            search_stats = evaluate_search_entries(entries)

    # Write report markdown & eval_cases.csv.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path = out_path.parent / "eval_cases.csv"
    csv_fields = [
        "case_id",
        "status",
        "link_ok",
        "link_confidence",
        "top1_t",
        "best_diff_s",
        "best_rank",
        "within_1_5s",
        "top1_rel",
        "match_ready_cnt",
        "frontal_ok",
        "total_s",
        "flags",
        "max_flag_scores",
        "error",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=csv_fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k) for k in csv_fields})

    link_pass = sum(1 for r in rows if r["link_ok"])
    link_fail = len(rows) - link_pass
    frontal_evals = [r for r in rows if r["frontal_ok"] is not None]
    frontal_pass = sum(1 for r in frontal_evals if r["frontal_ok"])
    frontal_fail = len(frontal_evals) - frontal_pass
    best_evals = [r for r in rows if r["within_1_5s"] is not None]
    best_pass = sum(1 for r in best_evals if r["within_1_5s"])
    best_fail = len(best_evals) - best_pass

    md: list[str] = [
        "# Strix Evaluation Report",
        "",
        f"- Date: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- Git commit: `{_git_commit_hash()}`",
        (
            f"- Versions: `torch={_pkg_version('torch')}`, `onnxruntime={_pkg_version('onnxruntime-gpu')}`, "
            f"`insightface={_pkg_version('insightface')}`, `open_clip={_pkg_version('open_clip_torch')}`"
        ),
        "",
        "## Summary",
        "",
        "| Metric | PASS | FAIL | Total |",
        "| --- | ---: | ---: | ---: |",
        f"| link_ok | {link_pass} | {link_fail} | {len(rows)} |",
        f"| frontal_ok | {frontal_pass} | {frontal_fail} | {len(frontal_evals)} |",
        f"| best_frame_within_1_5s | {best_pass} | {best_fail} | {len(best_evals)} |",
        "",
        "## Per-Case Results",
        "",
        "| case_id | status | link_ok | conf | top1_t | top1_rel | ready_cnt | frontal_ok | total_s | flags |",
        "| --- | --- | --- | --- | ---: | --- | ---: | --- | ---: | --- |",
    ]
    for r in rows:
        t1 = f"{r['top1_t']:.2f}" if r["top1_t"] is not None else "-"
        fok = str(r["frontal_ok"]) if r["frontal_ok"] is not None else "n/a"
        md.append(
            f"| {r['case_id']} | {r['status']} | {r['link_ok']} | {r['link_confidence']} | "
            f"{t1} | {r['top1_rel']} | {r['match_ready_cnt']} | {fok} | {r['total_s']:.2f} | {r['flags']} |"
        )

    if search_stats is not None:
        md.extend(["", "## Search Evaluation (Leave-One-Out)", ""])
        md.extend(
            [
                "| setting | n | top1_acc | top5_acc | mean_sim_correct | mean_sim_wrong | note |",
                "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for setting, st in search_stats.items():
            t1 = f"{st['top1_acc']:.3f}" if st["top1_acc"] is not None else "-"
            t5 = f"{st['top5_acc']:.3f}" if st["top5_acc"] is not None else "-"
            mc = f"{st['mean_sim_correct']:.3f}" if st["mean_sim_correct"] is not None else "-"
            mw = f"{st['mean_sim_wrong']:.3f}" if st["mean_sim_wrong"] is not None else "-"
            note = "small sample" if st["small_sample"] else "-"
            md.append(f"| {setting} | {st['n']} | {t1} | {t5} | {mc} | {mw} | {note} |")

    md.extend(["", "## Failures and Limits", ""])
    if failures:
        for f in failures:
            crops = ", ".join(f["crop_paths"]) if f["crop_paths"] else "none"
            md.append(f"- **{f['case_id']}** ({f['status']}): {f['reason']} | crops: {crops}")
    else:
        md.append("- No failed cases in this run.")

    out_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return rows, search_stats


def _print_console_tables(rows: list[dict[str, Any]], out_path: Path) -> None:
    link_pass = sum(1 for r in rows if r["link_ok"])
    frontal_evals = [r for r in rows if r["frontal_ok"] is not None]
    frontal_pass = sum(1 for r in frontal_evals if r["frontal_ok"])
    print(f"\nSummary: link_ok={link_pass}/{len(rows)}, frontal_ok={frontal_pass}/{len(frontal_evals)}")
    print(f"\n{'case_id':<12} {'status':<6} {'link_ok':<7} {'conf':<6} {'top1_t':>7} {'rel':<6} {'ready':>5} {'f_ok':<5} {'s':>6}  flags")
    print("-" * 82)
    for r in rows:
        t1 = f"{r['top1_t']:.2f}" if r["top1_t"] is not None else "-"
        fok = str(r["frontal_ok"]) if r["frontal_ok"] is not None else "n/a"
        print(
            f"{r['case_id']:<12} {r['status']:<6} {str(r['link_ok']):<7} {r['link_confidence']:<6} "
            f"{t1:>7} {r['top1_rel']:<6} {r['match_ready_cnt']:>5} {fok:<5} {r['total_s']:>6.2f}  {r['flags']}"
        )
    print(f"\nSaved report: {out_path}")
    print(f"Saved CSV: {out_path.parent / 'eval_cases.csv'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run end-to-end evaluation harness over a manifest CSV.")
    parser.add_argument("--manifest", type=Path, required=True, help="Path to manifest.csv")
    parser.add_argument("--people", type=Path, default=None, help="Optional people.csv for search eval")
    parser.add_argument("--out", type=Path, default=Path("docs/eval_report.md"), help="Output markdown report path")
    args = parser.parse_args()

    try:
        rows, _ = run_evaluation(args.manifest, args.people, args.out)
    except ValueError as exc:
        print(f"INVALID MANIFEST/PEOPLE CSV: {exc}", file=sys.stderr)
        return 2

    _print_console_tables(rows, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
