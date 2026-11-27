"""Verify offline readiness: all ML models load offline and demo_pack is complete."""

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.contract import IndexResult, load_result
from scripts import verify_models


def verify_demo_pack(pack_dir: Path) -> list[str]:
    """Return a list of missing or invalid items in pack_dir (empty if complete)."""
    missing: list[str] = []
    manifest_path = pack_dir / "manifest.json"
    if not manifest_path.exists():
        return [f"Missing manifest: {manifest_path}"]

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for case in manifest.get("cases", []):
        rj = pack_dir / case["result_json"]
        if not rj.exists():
            missing.append(f"Missing case result.json: {rj}")
            continue
        res = load_result(rj)
        for fr in res.best_frames:
            for p_str in (fr.frame_path, fr.embedding_path, fr.crop_path):
                if p_str and not (pack_dir / p_str).exists():
                    missing.append(f"Missing frame artifact: {pack_dir / p_str}")
            if fr.enhancement is not None:
                ep = pack_dir / fr.enhancement.enhanced_path
                if not ep.exists():
                    missing.append(f"Missing enhanced artifact: {ep}")

    for idx_entry in manifest.get("indexes", []):
        ij = pack_dir / idx_entry["index_json"]
        iz = pack_dir / idx_entry["index_npz"]
        if not ij.exists():
            missing.append(f"Missing index.json: {ij}")
            continue
        if not iz.exists():
            missing.append(f"Missing index.npz: {iz}")
        idx_res = IndexResult.model_validate_json(ij.read_text(encoding="utf-8"))
        for tr in idx_res.tracks:
            for f in tr.faces:
                for p_str in (f.frame_path, f.crop_path, f.embedding_path):
                    if not (pack_dir / p_str).exists():
                        missing.append(f"Missing index artifact: {pack_dir / p_str}")

    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify offline models and demo_pack completeness.")
    parser.add_argument("--demo-pack", type=Path, default=Path("demo_pack"), help="Path to demo_pack directory")
    args = parser.parse_args()

    models_rc = verify_models.main()
    missing = verify_demo_pack(args.demo_pack)
    if missing:
        print("MISSING/INVALID in demo_pack:")
        for item in missing:
            print(f"  - {item}")
        return 1

    print(f"OK: demo_pack verified complete ({args.demo_pack})")
    return 0 if models_rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
