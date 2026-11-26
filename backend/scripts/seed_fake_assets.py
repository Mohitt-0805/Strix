"""Pre-generate fake pipeline JPG and 512-d .npy assets for manual testing."""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.services.fake_assets import materialize_fake_assets  # noqa: E402
from pipeline.fake_pipeline import SAMPLE_RESULT_PATH  # noqa: E402
from pipeline.contract import load_result  # noqa: E402


def main() -> int:
    """Materialize fake assets under DATA_DIR/outputs/<clip_id>/run_<run_id>/."""
    parser = argparse.ArgumentParser(description="Seed placeholder fake pipeline assets.")
    parser.add_argument("--clip-id", required=True, help="Clip UUID or identifier")
    parser.add_argument("--run-id", type=int, default=1, help="Run ID")
    parser.add_argument(
        "--filename",
        default="A_sample.mp4",
        help="Original filename (prefix before '_' seeds person_vector)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Override DATA_DIR (defaults to configured DATA_DIR)",
    )
    args = parser.parse_args()

    data_dir = args.data_dir if args.data_dir is not None else get_settings().resolved_data_dir
    sample = load_result(SAMPLE_RESULT_PATH)
    updated = materialize_fake_assets(
        sample,
        clip_id=args.clip_id,
        run_id=args.run_id,
        original_filename=args.filename,
        data_dir=data_dir,
    )
    out_folder = data_dir.resolve() / "outputs" / args.clip_id / f"run_{args.run_id}"
    print(f"Materialized {len(updated.best_frames)} fake frame assets in {out_folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
