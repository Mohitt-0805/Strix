"""Build a self-contained demo_pack directory with relative paths."""

import argparse
import json
from pathlib import Path
import shutil
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.adapter import get_index_clip, get_run
from pipeline.enhance import _expand_box_with_margin, enhance_frame
from scripts.run_eval import load_manifest


def _copy_rel(src: str | Path, dest_dir: Path, pack_root: Path) -> str:
    src_p = Path(src)
    dest_p = dest_dir / src_p.name
    dest_dir.mkdir(parents=True, exist_ok=True)
    if src_p.resolve() != dest_p.resolve():
        shutil.copy2(src_p, dest_p)
    return dest_p.relative_to(pack_root).as_posix()


def build_demo_pack(manifest_path: Path, out_dir: Path) -> Path:
    """Run pipeline & index_clip on manifest cases and write portable demo_pack."""
    import numpy as np

    cases = load_manifest(manifest_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_fn = get_run()
    index_fn = get_index_clip()

    manifest_cases: list[dict[str, object]] = []
    manifest_indexes: list[dict[str, object]] = []
    seen_clips: dict[str, dict[str, object]] = {}

    for case in cases:
        case_dir = out_dir / case.case_id
        case_dir.mkdir(parents=True, exist_ok=True)

        res = run_fn(
            clip_path=case.clip,
            tx_offset_sec=case.tx_sec,
            window_sec=case.window_sec,
            atm_id=case.atm_id,
            out_dir=out_dir / "_tmp_run",
        )

        new_frames = []
        for fr in res.best_frames:
            rel_frame = _copy_rel(fr.frame_path, case_dir, out_dir) if Path(fr.frame_path).exists() else fr.frame_path
            rel_emb = _copy_rel(fr.embedding_path, case_dir, out_dir) if Path(fr.embedding_path).exists() else fr.embedding_path
            rel_crop = (
                _copy_rel(fr.crop_path, case_dir, out_dir)
                if fr.crop_path and Path(fr.crop_path).exists()
                else None
            )

            enh_obj = fr.enhancement
            enhanced_flag = fr.enhanced
            if fr.match_ready and fr.face_box is not None and Path(fr.frame_path).exists():
                box = _expand_box_with_margin(fr.face_box, margin=0.20)
                enh = enhance_frame(fr.frame_path, box, method="lanczos", scale=4, out_dir=case_dir)
                rel_enh = Path(enh.enhanced_path).relative_to(out_dir).as_posix()
                enh_obj = enh.model_copy(update={"enhanced_path": rel_enh})
                enhanced_flag = True

            new_frames.append(
                fr.model_copy(
                    update={
                        "frame_path": rel_frame,
                        "embedding_path": rel_emb,
                        "crop_path": rel_crop,
                        "enhanced": enhanced_flag,
                        "enhancement": enh_obj,
                    }
                )
            )

        res_rel = res.model_copy(update={"best_frames": new_frames})
        res_json_path = case_dir / "result.json"
        res_json_path.write_text(res_rel.model_dump_json(indent=2), encoding="utf-8")

        manifest_cases.append(
            {
                "case_id": case.case_id,
                "clip_name": Path(case.clip).name,
                "clip_stem": Path(case.clip).stem,
                "atm_id": case.atm_id,
                "tx_sec": case.tx_sec,
                "window_sec": case.window_sec,
                "result_json": res_json_path.relative_to(out_dir).as_posix(),
            }
        )

        if case.clip not in seen_clips:
            clip_stem = Path(case.clip).stem
            idx_dir = out_dir / clip_stem / "index"
            idx_dir.mkdir(parents=True, exist_ok=True)
            idx_res = index_fn(clip_path=case.clip, out_dir=out_dir / "_tmp_idx")

            new_tracks = []
            new_meta = []
            for tr in idx_res.tracks:
                new_faces = []
                for f in tr.faces:
                    rf = _copy_rel(f.frame_path, idx_dir, out_dir)
                    rc = _copy_rel(f.crop_path, idx_dir, out_dir)
                    re = _copy_rel(f.embedding_path, idx_dir, out_dir)
                    new_faces.append(f.model_copy(update={"frame_path": rf, "crop_path": rc, "embedding_path": re}))
                    new_meta.append(
                        {
                            "track_id": tr.track_id,
                            "t": f.t,
                            "quality_score": f.quality_score,
                            "reliability": f.reliability,
                            "match_ready": f.match_ready,
                            "flags": f.flags,
                            "face_box": f.face_box,
                            "crop_path": rc,
                            "frame_path": rf,
                            "embedding_path": re,
                        }
                    )
                new_tracks.append(tr.model_copy(update={"faces": new_faces}))

            npz_src = np.load(idx_res.index_npz_path)
            idx_npz_path = idx_dir / "index.npz"
            np.savez(
                str(idx_npz_path),
                embeddings=npz_src["embeddings"],
                metadata_json=np.array(json.dumps(new_meta)),
            )

            idx_json_path = idx_dir / "index.json"
            idx_rel = idx_res.model_copy(
                update={
                    "tracks": new_tracks,
                    "index_npz_path": idx_npz_path.relative_to(out_dir).as_posix(),
                    "index_json_path": idx_json_path.relative_to(out_dir).as_posix(),
                }
            )
            idx_json_path.write_text(idx_rel.model_dump_json(indent=2), encoding="utf-8")

            entry = {
                "clip_name": Path(case.clip).name,
                "clip_stem": clip_stem,
                "start_sec": idx_rel.start_sec,
                "end_sec": idx_rel.end_sec,
                "index_json": idx_json_path.relative_to(out_dir).as_posix(),
                "index_npz": idx_npz_path.relative_to(out_dir).as_posix(),
            }
            seen_clips[case.clip] = entry
            manifest_indexes.append(entry)

    # Clean temporary staging directories.
    for tmp_sub in ("_tmp_run", "_tmp_idx"):
        tmp_p = out_dir / tmp_sub
        if tmp_p.exists():
            shutil.rmtree(tmp_p)

    manifest_out = out_dir / "manifest.json"
    manifest_out.write_text(
        json.dumps({"cases": manifest_cases, "indexes": manifest_indexes}, indent=2),
        encoding="utf-8",
    )
    return manifest_out


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a portable demo_pack from manifest.csv.")
    parser.add_argument("--manifest", type=Path, default=Path("data/samples/manifest.csv"))
    parser.add_argument("--out", type=Path, default=Path("demo_pack"))
    args = parser.parse_args()

    manifest_out = build_demo_pack(args.manifest, args.out)
    print(f"Created demo pack manifest: {manifest_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
