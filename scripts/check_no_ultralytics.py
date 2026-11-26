"""Fail with exit code 1 if 'ultralytics' appears in installed Python packages."""

import importlib.metadata
import sys


def main() -> int:
    """Check installed distributions for any package containing 'ultralytics'."""
    matches = sorted(
        dist.metadata["Name"]
        for dist in importlib.metadata.distributions()
        if dist.metadata["Name"] and "ultralytics" in dist.metadata["Name"].lower()
    )
    if matches:
        print(f"ERROR: Forbidden package(s) installed: {', '.join(matches)}", file=sys.stderr)
        return 1

    print("OK: No ultralytics packages installed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
