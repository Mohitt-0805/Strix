"""Evaluate detection, embedding cosine, and retrieval across downscaled/degraded/enhanced crops."""

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.compare import search_with_enhancement
from pipeline.contract import load_result
from pipeline.embeddings import cosine, embed_crop, load_embedding
from pipeline.enhance import enhance_frame


DEGRADATIONS = ("none", "blur", "dark", "jpeg20", "blur+jpeg20")


def load_identities(path: Path | None, track_ids: list[int]) -> dict[int, str]:
    """Load track_id -> identity label JSON; unlisted tracks default to 'track_<id>'."""
    raw: dict[str, str] = {}
    if path is not None:
        raw = json.loads(path.read_text(encoding="utf-8"))
    mapping: dict[int, str] = {}
    for tid in sorted(set(int(t) for t in track_ids)):
        mapping[tid] = str(raw.get(str(tid), f"track_{tid}"))
    return mapping


def apply_degradation(bgr_img: Any, kind: str) -> Any:
    """Apply a named degradation to a BGR uint8 crop."""
    import cv2
    import numpy as np

    if kind == "none":
        return bgr_img
    if kind == "blur":
        return cv2.GaussianBlur(bgr_img, (0, 0), sigmaX=1.5, sigmaY=1.5)
    if kind == "dark":
        norm = bgr_img.astype(np.float32) / 255.0
        return np.clip((norm ** 2.2) * 255.0, 0, 255).astype(np.uint8)
    if kind == "jpeg20":
        ok, buf = cv2.imencode(".jpg", bgr_img, [int(cv2.IMWRITE_JPEG_QUALITY), 20])
        return cv2.imdecode(buf, cv2.IMREAD_COLOR) if ok else bgr_img
    if kind == "blur+jpeg20":
        blurred = cv2.GaussianBlur(bgr_img, (0, 0), sigmaX=1.5, sigmaY=1.5)
        ok, buf = cv2.imencode(".jpg", blurred, [int(cv2.IMWRITE_JPEG_QUALITY), 20])
        return cv2.imdecode(buf, cv2.IMREAD_COLOR) if ok else blurred
    raise ValueError(f"Unknown degradation: {kind!r}")


def evaluate_leave_one_out(
    query_vec: Any,
    query_track_id: int,
    query_t: float,
    index_embeddings: Any,
    index_metadata: list[dict[str, Any]],
    identities: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Evaluate leave-one-out retrieval using identity labels (setting 1: drop own row; setting 2: drop own identity)."""
    import numpy as np

    def _id(tid: int) -> str:
        if identities and int(tid) in identities:
            return identities[int(tid)]
        return f"track_{int(tid)}"

    q = np.asarray(query_vec, dtype=np.float32).ravel()
    q_norm = float(np.linalg.norm(q))
    if q_norm > 0.0:
        q = q / q_norm

    sims = (index_embeddings @ q).tolist() if index_embeddings.shape[0] > 0 else []
    query_identity = _id(query_track_id)

    # Identify own row: same track_id and closest timestamp within 0.05 s.
    own_idx: int | None = None
    best_dt = 0.05
    for idx, meta in enumerate(index_metadata):
        if int(meta["track_id"]) == int(query_track_id):
            dt = abs(float(meta["t"]) - float(query_t))
            if dt <= best_dt:
                best_dt = dt
                own_idx = idx

    # Setting 1: remove own row.
    rem_s1 = [
        (float(sim), meta)
        for idx, (sim, meta) in enumerate(zip(sims, index_metadata))
        if idx != own_idx
    ]
    rem_s1.sort(key=lambda x: x[0], reverse=True)

    same_sims = [sim for sim, meta in rem_s1 if _id(int(meta["track_id"])) == query_identity]
    other_rows = [(sim, meta) for sim, meta in rem_s1 if _id(int(meta["track_id"])) != query_identity]

    insufficient_same_rows = len(same_sims) == 0
    top1_correct: bool | None = (
        None
        if insufficient_same_rows
        else bool(rem_s1 and _id(int(rem_s1[0][1]["track_id"])) == query_identity)
    )
    best_same = None if insufficient_same_rows else max(same_sims)
    best_other = other_rows[0][0] if other_rows else None
    best_other_meta = other_rows[0][1] if other_rows else None
    margin = (best_same - best_other) if (best_same is not None and best_other is not None) else None

    # Setting 2: remove all rows of own identity.
    best_wrong = best_other

    return {
        "top1_correct": top1_correct,
        "insufficient_same_rows": insufficient_same_rows,
        "same_row_count": len(same_sims),
        "best_same": best_same,
        "best_other": best_other,
        "best_other_meta": best_other_meta,
        "margin": margin,
        "best_wrong": best_wrong,
    }


def _save_failure_panel(
    out_path: Path,
    orig_bgr: Any,
    down_bgr: Any,
    enh_bgr: Any,
    wrong_bgr: Any | None,
    title: str,
) -> None:
    from PIL import Image, ImageDraw
    import cv2

    def _to_pil(bgr: Any | None, size: int = 128) -> Image.Image:
        if bgr is None:
            im = Image.new("RGB", (size, size), color=(50, 50, 50))
            ImageDraw.Draw(im).text((8, size // 2 - 6), "missing", fill=(200, 200, 200))
            return im
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        im = Image.fromarray(rgb)
        im.thumbnail((size, size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (size, size), color=(30, 30, 30))
        canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
        return canvas

    cell = 132
    pad = 8
    sheet = Image.new("RGB", (4 * (cell + pad) + pad, cell + 44), color=(22, 22, 26))
    draw = ImageDraw.Draw(sheet)
    draw.text((pad, 4), title[:80], fill=(255, 220, 120))
    labels = ["original", "downscaled", "enhanced", "best_wrong"]
    imgs = [_to_pil(orig_bgr, cell), _to_pil(down_bgr, cell), _to_pil(enh_bgr, cell), _to_pil(wrong_bgr, cell)]
    for idx, (lbl, im) in enumerate(zip(labels, imgs)):
        x0 = idx * (cell + pad) + pad
        sheet.paste(im, (x0, 20))
        draw.text((x0, 22 + cell), lbl, fill=(200, 230, 255))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, format="JPEG", quality=92)


def _run_basic(index_dir: Path, result_json: Path, sizes: list[int], scales: list[int]) -> int:
    import cv2

    res = load_result(result_json)
    ready_frames = [fr for fr in res.best_frames if fr.match_ready and fr.crop_path and Path(fr.crop_path).exists()]
    if not ready_frames:
        print("No match_ready frames with existing crop_path found.")
        return 1

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmp_dir = Path(tmpdir_str)
        refs = []
        for fr in ready_frames:
            orig_emb = load_embedding(Path(fr.embedding_path))
            ref_search = search_with_enhancement(index_dir, fr.crop_path, original_embedding=orig_emb, top_k=1)
            ref_top1 = ref_search.matches[0].track_id if ref_search.matches else None
            crop_bgr = cv2.imread(str(fr.crop_path))
            if crop_bgr is not None:
                refs.append((fr, orig_emb, ref_top1, crop_bgr))

        for target_w in sizes:
            variants = ["downscaled"] + [f"lanczos_x{s}" for s in scales]
            stats: dict[str, dict[str, list[float]]] = {v: {"det": [], "cos": [], "top1_same": []} for v in variants}

            for fr, orig_emb, ref_top1, crop_bgr in refs:
                ch, cw = crop_bgr.shape[:2]
                target_h = max(8, int(round(ch * (float(target_w) / max(1, cw)))))
                down_bgr = cv2.resize(crop_bgr, (target_w, target_h), interpolation=cv2.INTER_AREA)
                down_path = tmp_dir / f"{fr.frame_id}_w{target_w}.jpg"
                cv2.imwrite(str(down_path), down_bgr)

                down_vec = embed_crop(down_bgr)
                stats["downscaled"]["det"].append(1.0 if down_vec is not None else 0.0)
                if down_vec is not None:
                    stats["downscaled"]["cos"].append(cosine(down_vec, orig_emb))

                s_down = search_with_enhancement(index_dir, down_path, original_embedding=down_vec, top_k=1)
                top1_down = s_down.matches[0].track_id if s_down.matches else None
                stats["downscaled"]["top1_same"].append(1.0 if (ref_top1 is not None and top1_down == ref_top1) else 0.0)

                for scale in scales:
                    vname = f"lanczos_x{scale}"
                    enh_dir = tmp_dir / f"enh_{fr.frame_id}_w{target_w}_x{scale}"
                    enh = enhance_frame(down_path, [0, 0, target_w, target_h], method="lanczos", scale=scale, out_dir=enh_dir)
                    enh_bgr = cv2.imread(enh.enhanced_path)
                    enh_vec = embed_crop(enh_bgr) if enh_bgr is not None else None
                    stats[vname]["det"].append(1.0 if enh_vec is not None else 0.0)
                    if enh_vec is not None:
                        stats[vname]["cos"].append(cosine(enh_vec, orig_emb))

                    s_enh = search_with_enhancement(
                        index_dir,
                        down_path,
                        enhanced_crop_path=enh.enhanced_path,
                        original_embedding=down_vec,
                        enhanced_embedding=enh_vec,
                        top_k=1,
                    )
                    top1_enh = s_enh.matches[0].track_id if s_enh.matches else None
                    stats[vname]["top1_same"].append(1.0 if (ref_top1 is not None and top1_enh == ref_top1) else 0.0)

            print(f"\n=== Target width: {target_w} px (n={len(refs)} frames) ===")
            print(f"{'variant':<14}  {'det_rate':>8}  {'mean_cos':>8}  {'top1_same':>9}")
            print("-" * 46)
            for vname in variants:
                det_r = sum(stats[vname]["det"]) / max(1, len(stats[vname]["det"]))
                cos_vals = stats[vname]["cos"]
                mean_c = f"{sum(cos_vals) / len(cos_vals):.3f}" if cos_vals else "-"
                top1_r = sum(stats[vname]["top1_same"]) / max(1, len(stats[vname]["top1_same"]))
                print(f"{vname:<14}  {det_r:>8.2f}  {mean_c:>8}  {top1_r:>9.2f}")
    return 0


def _run_hard(
    index_dir: Path,
    result_json: Path,
    sizes: list[int],
    scales: list[int],
    identities_path: Path | None = None,
) -> int:
    import cv2
    import numpy as np

    res = load_result(result_json)
    ready_frames = [fr for fr in res.best_frames if fr.match_ready and fr.crop_path and Path(fr.crop_path).exists()]
    if not ready_frames:
        print("No match_ready frames with existing crop_path found.")
        return 1

    npz = np.load(index_dir / "index.npz")
    idx_embs = np.asarray(npz["embeddings"], dtype=np.float32)
    raw_meta = npz["metadata_json"].item()
    idx_meta: list[dict[str, Any]] = json.loads(raw_meta.decode("utf-8") if isinstance(raw_meta, bytes) else str(raw_meta))

    all_tids = [int(m["track_id"]) for m in idx_meta]
    identities = load_identities(identities_path, all_tids)
    rows_per_id: dict[str, int] = {}
    for m in idx_meta:
        lbl = identities[int(m["track_id"])]
        rows_per_id[lbl] = rows_per_id.get(lbl, 0) + 1

    # Determine query person's track and identity in the index.
    query_track_id: int | None = None
    first_emb = load_embedding(Path(ready_frames[0].embedding_path))
    first_loo = evaluate_leave_one_out(first_emb, -999, 0.0, idx_embs, idx_meta, identities=identities)
    if first_loo["best_other_meta"] is not None:
        query_track_id = int(first_loo["best_other_meta"]["track_id"])
    if query_track_id is None:
        print("Could not determine query track in index.")
        return 1
    query_identity = identities.get(query_track_id, f"track_{query_track_id}")

    print("=== Identity Map & Index Row Counts ===")
    for tid in sorted(identities):
        lbl = identities[tid]
        print(f"  track {tid:>2} -> {lbl} (identity_rows={rows_per_id.get(lbl, 0)})")

    all_sizes = sorted(set(sizes) | {24, 30, 36})
    variants = ["downscaled"] + [f"lanczos_x{s}" for s in scales]
    md_lines: list[str] = [
        "# Enhancement Evaluation (Hard Mode)",
        "",
        f"- Index: `{index_dir}` (`N={len(idx_meta)}` embeddings)",
        f"- Query result: `{result_json}` (`query_track_id={query_track_id}`, `query_identity={query_identity}`, `n_query_frames={len(ready_frames)}`)",
        "",
        "## Identity Map Used",
        "",
        "| track_id | identity | index_rows |",
        "| ---: | --- | ---: |",
    ]
    for tid in sorted(identities):
        lbl = identities[tid]
        md_lines.append(f"| {tid} | {lbl} | {rows_per_id.get(lbl, 0)} |")
    md_lines.append("")

    failures: list[dict[str, Any]] = []
    fail_dir = REPO_ROOT / "data" / "outputs" / "eval_failures"

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmp_dir = Path(tmpdir_str)

        # 1) Leave-one-out across sizes and degradations.
        for target_w in all_sizes:
            for deg in DEGRADATIONS:
                agg: dict[str, dict[str, list[float]]] = {
                    v: {"det": [], "top1": [], "same": [], "other": [], "margin": []} for v in variants
                }
                na_same_seen = False

                for fr in ready_frames:
                    crop_bgr = cv2.imread(str(fr.crop_path))
                    if crop_bgr is None:
                        continue
                    ch, cw = crop_bgr.shape[:2]
                    target_h = max(8, int(round(ch * (float(target_w) / max(1, cw)))))
                    down_raw = cv2.resize(crop_bgr, (target_w, target_h), interpolation=cv2.INTER_AREA)
                    down_deg = apply_degradation(down_raw, deg)
                    down_path = tmp_dir / f"{fr.frame_id}_w{target_w}_{deg}.jpg"
                    cv2.imwrite(str(down_path), down_deg)

                    down_vec = embed_crop(down_deg)
                    agg["downscaled"]["det"].append(1.0 if down_vec is not None else 0.0)
                    loo_down = None
                    if down_vec is not None:
                        loo_down = evaluate_leave_one_out(
                            down_vec, query_track_id, fr.timestamp_sec, idx_embs, idx_meta, identities=identities
                        )
                        if loo_down["insufficient_same_rows"]:
                            na_same_seen = True
                        if loo_down["top1_correct"] is not None:
                            agg["downscaled"]["top1"].append(1.0 if loo_down["top1_correct"] else 0.0)
                        if loo_down["best_same"] is not None:
                            agg["downscaled"]["same"].append(float(loo_down["best_same"]))
                        if loo_down["best_other"] is not None:
                            agg["downscaled"]["other"].append(float(loo_down["best_other"]))
                        if loo_down["margin"] is not None:
                            agg["downscaled"]["margin"].append(float(loo_down["margin"]))

                    for scale in scales:
                        vname = f"lanczos_x{scale}"
                        enh_dir = tmp_dir / f"enh_{fr.frame_id}_w{target_w}_{deg}_x{scale}"
                        enh = enhance_frame(down_path, [0, 0, target_w, target_h], method="lanczos", scale=scale, out_dir=enh_dir)
                        enh_bgr = cv2.imread(enh.enhanced_path)
                        enh_vec = embed_crop(enh_bgr) if enh_bgr is not None else None
                        agg[vname]["det"].append(1.0 if enh_vec is not None else 0.0)
                        if enh_vec is not None:
                            loo_enh = evaluate_leave_one_out(
                                enh_vec, query_track_id, fr.timestamp_sec, idx_embs, idx_meta, identities=identities
                            )
                            if loo_enh["insufficient_same_rows"]:
                                na_same_seen = True
                            if loo_enh["top1_correct"] is not None:
                                agg[vname]["top1"].append(1.0 if loo_enh["top1_correct"] else 0.0)
                            if loo_enh["best_same"] is not None:
                                agg[vname]["same"].append(float(loo_enh["best_same"]))
                            if loo_enh["best_other"] is not None:
                                agg[vname]["other"].append(float(loo_enh["best_other"]))
                            if loo_enh["margin"] is not None:
                                agg[vname]["margin"].append(float(loo_enh["margin"]))

                            if loo_down is not None and len(failures) < 3:
                                worse_rank = (
                                    loo_down["top1_correct"] is True and loo_enh["top1_correct"] is False
                                )
                                higher_wrong = (
                                    loo_down["best_other"] is not None
                                    and loo_enh["best_other"] is not None
                                    and loo_enh["best_other"] > loo_down["best_other"] + 0.02
                                )
                                if worse_rank or higher_wrong:
                                    wrong_meta = loo_enh["best_other_meta"]
                                    wrong_bgr = (
                                        cv2.imread(str(wrong_meta["crop_path"]))
                                        if wrong_meta and wrong_meta.get("crop_path")
                                        else None
                                    )
                                    fail_path = fail_dir / f"fail_{len(failures) + 1}_{fr.frame_id}_w{target_w}_{deg}_{vname}.jpg"
                                    _save_failure_panel(
                                        fail_path,
                                        crop_bgr,
                                        down_deg,
                                        enh_bgr,
                                        wrong_bgr,
                                        f"{fr.frame_id} w={target_w} {deg} {vname}",
                                    )
                                    failures.append(
                                        {
                                            "frame_id": fr.frame_id,
                                            "size": target_w,
                                            "deg": deg,
                                            "variant": vname,
                                            "path": str(fail_path),
                                        }
                                    )

                hdr = f"=== Leave-One-Out | width={target_w}px | deg={deg} | n={len(ready_frames)} ==="
                print(f"\n{hdr}")
                print(f"{'variant':<12} {'det':>5} {'top1_ok':>7} {'same':>6} {'wrong':>6} {'margin':>7}")
                print("-" * 48)
                md_lines.extend(
                    [
                        f"### width={target_w}px, deg={deg} (n={len(ready_frames)})",
                        "",
                        "| variant | det | top1_ok | best_same | best_wrong | margin |",
                        "| --- | ---: | ---: | ---: | ---: | ---: |",
                    ]
                )

                def _mean_str(vals: list[float], is_na: bool = False) -> str:
                    if is_na and not vals:
                        return "n/a"
                    return f"{sum(vals) / len(vals):.3f}" if vals else "n/a"

                for vname in variants:
                    det_s = _mean_str(agg[vname]["det"])
                    t1_s = _mean_str(agg[vname]["top1"], na_same_seen)
                    same_s = _mean_str(agg[vname]["same"], na_same_seen)
                    oth_s = _mean_str(agg[vname]["other"])
                    mrg_s = _mean_str(agg[vname]["margin"], na_same_seen)
                    print(f"{vname:<12} {det_s:>5} {t1_s:>7} {same_s:>6} {oth_s:>6} {mrg_s:>7}")
                    md_lines.append(f"| {vname} | {det_s} | {t1_s} | {same_s} | {oth_s} | {mrg_s} |")
                md_lines.append("")

        # 2) Distractors: all index faces whose identity != query_identity.
        distractors = [
            m for m in idx_meta
            if identities[int(m["track_id"])] != query_identity
            and m.get("crop_path")
            and Path(m["crop_path"]).exists()
        ]
        full_det_ok = 0
        for dm in distractors:
            d_full = cv2.imread(str(dm["crop_path"]))
            if d_full is not None and embed_crop(d_full) is not None:
                full_det_ok += 1

        print(
            f"\n=== Distractors (identity != {query_identity} | n={len(distractors)} | "
            f"undegraded full-size det={full_det_ok}/{len(distractors)}) ==="
        )
        print(f"{'deg':<12} {'variant':<12} {'embedded':>9} {'wrong_match_rate':>20}")
        print("-" * 58)
        md_lines.extend(
            [
                f"## Distractors (n={len(distractors)}, undegraded full-size det={full_det_ok}/{len(distractors)})",
                "",
                "| deg | variant | n_embedded | wrong_match_rate |",
                "| --- | --- | ---: | ---: |",
            ]
        )

        for deg in DEGRADATIONS:
            dist_stats: dict[str, dict[str, list[float]]] = {v: {"det": [], "wrong": []} for v in variants}
            for dm in distractors:
                d_bgr = cv2.imread(str(dm["crop_path"]))
                if d_bgr is None:
                    continue
                dh, dw = d_bgr.shape[:2]
                tw = 40
                th = max(8, int(round(dh * (tw / max(1, dw)))))
                d_down = apply_degradation(cv2.resize(d_bgr, (tw, th), interpolation=cv2.INTER_AREA), deg)
                d_path = tmp_dir / f"dist_{deg}_{dm['track_id']}_{int(dm['t']*1000)}.jpg"
                cv2.imwrite(str(d_path), d_down)

                d_vec = embed_crop(d_down)
                dist_stats["downscaled"]["det"].append(1.0 if d_vec is not None else 0.0)
                if d_vec is not None:
                    loo_d = evaluate_leave_one_out(
                        d_vec, int(dm["track_id"]), float(dm["t"]), idx_embs, idx_meta, identities=identities
                    )
                    hit_q = (
                        loo_d["best_other_meta"] is not None
                        and identities[int(loo_d["best_other_meta"]["track_id"])] == query_identity
                    )
                    dist_stats["downscaled"]["wrong"].append(1.0 if hit_q else 0.0)

                for scale in scales:
                    vname = f"lanczos_x{scale}"
                    enh = enhance_frame(
                        d_path, [0, 0, tw, th], method="lanczos", scale=scale, out_dir=tmp_dir / f"de_{deg}_{vname}"
                    )
                    e_bgr = cv2.imread(enh.enhanced_path)
                    e_vec = embed_crop(e_bgr) if e_bgr is not None else None
                    dist_stats[vname]["det"].append(1.0 if e_vec is not None else 0.0)
                    if e_vec is not None:
                        loo_e = evaluate_leave_one_out(
                            e_vec, int(dm["track_id"]), float(dm["t"]), idx_embs, idx_meta, identities=identities
                        )
                        hit_q = (
                            loo_e["best_other_meta"] is not None
                            and identities[int(loo_e["best_other_meta"]["track_id"])] == query_identity
                        )
                        dist_stats[vname]["wrong"].append(1.0 if hit_q else 0.0)

            for vname in variants:
                n_emb = int(sum(dist_stats[vname]["det"]))
                n_tot = len(dist_stats[vname]["det"])
                emb_str = f"{n_emb}/{n_tot}"
                w_vals = dist_stats[vname]["wrong"]
                if n_emb < 5:
                    w_str = "too few to conclude"
                else:
                    w_str = f"{sum(w_vals) / len(w_vals):.3f}"
                print(f"{deg:<12} {vname:<12} {emb_str:>9} {w_str:>20}")
                md_lines.append(f"| {deg} | {vname} | {emb_str} | {w_str} |")

    print()
    md_lines.append("")
    if failures:
        print("Failure examples (enhanced worse than downscaled):")
        md_lines.append("## Failure Examples")
        for f in failures:
            line = f"  {f['frame_id']} | width={f['size']} | deg={f['deg']} | {f['variant']} -> {f['path']}"
            print(line)
            md_lines.append(f"- {line.strip()}")
    else:
        msg = "No cases where enhancement made the match worse"
        print(msg)
        md_lines.append(msg)

    report_path = REPO_ROOT / "docs" / "eval_enhancement.md"
    report_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(f"Saved report: {report_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate downscaled vs enhanced crops against original embeddings.")
    parser.add_argument("index_dir", type=Path, help="Index directory containing index.npz")
    parser.add_argument("result_json", type=Path, help="result.json from run_pipeline")
    parser.add_argument("--sizes", type=int, nargs="+", default=[40, 50, 60, 80], help="Target widths in px")
    parser.add_argument("--scales", type=int, nargs="+", default=[2, 4], help="Enhancement scales")
    parser.add_argument("--hard", action="store_true", help="Run hard mode with small sizes, degradations, LOO, distractors")
    parser.add_argument("--identities", type=Path, default=None, help="JSON mapping track_id -> person label")
    args = parser.parse_args()

    if args.hard:
        return _run_hard(args.index_dir, args.result_json, args.sizes, args.scales, args.identities)
    return _run_basic(args.index_dir, args.result_json, args.sizes, args.scales)


if __name__ == "__main__":
    raise SystemExit(main())
