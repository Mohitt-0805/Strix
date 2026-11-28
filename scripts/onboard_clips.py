"""Inspect, validate, and onboard organiser video clips without modifying originals."""

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.frames import _parse_fps, iter_sampled_frames, video_info
from scripts.check_timestamps import measure_drift

VIDEO_EXTENSIONS = {
    ".mp4",
    ".avi",
    ".mkv",
    ".mov",
    ".m4v",
    ".webm",
    ".ts",
    ".flv",
    ".wmv",
    ".mpg",
    ".mpeg",
    ".3gp",
}

MANIFEST_COLUMNS = [
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
]


def _ist_from_creation_time(raw_ct: str | None) -> str:
    """Convert an ISO/ffprobe creation_time tag string to Asia/Kolkata."""
    if not raw_ct:
        return "N/A"
    cleaned = raw_ct.strip()
    try:
        iso_str = cleaned[:-1] + "+00:00" if cleaned.endswith("Z") else cleaned
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")
    except Exception:
        return f"unparseable ({cleaned})"


def _probe_clip(clip_path: Path) -> dict[str, Any]:
    """Gather detailed ffprobe metadata plus pipeline.frames.video_info summary."""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(clip_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        return {"probe_error": f"ffprobe failed (rc={proc.returncode})"}

    payload = json.loads(proc.stdout)
    fmt = payload.get("format") or {}
    streams = payload.get("streams") or []
    vstream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if vstream is None:
        return {"probe_error": "No video stream found"}

    audio_present = any(s.get("codec_type") == "audio" for s in streams)
    raw_ct = (fmt.get("tags") or {}).get("creation_time") or (vstream.get("tags") or {}).get("creation_time")

    try:
        vinfo = video_info(clip_path)
        rotation = int(vinfo["rotation"])
        display_w = int(vinfo["display_width"])
        display_h = int(vinfo["display_height"])
        vfr_suspected = bool(vinfo["vfr_suspected"])
        dur = float(vinfo["duration_sec"])
    except Exception:
        rotation = 0
        display_w = int(vstream.get("width", 0))
        display_h = int(vstream.get("height", 0))
        r_f = _parse_fps(str(vstream.get("r_frame_rate") or "0/1"))
        a_f = _parse_fps(str(vstream.get("avg_frame_rate") or "0/1"))
        vfr_suspected = bool(r_f > 0 and a_f > 0 and abs(a_f - r_f) / max(r_f, 1e-9) > 0.01)
        dur = float(vstream.get("duration") or fmt.get("duration") or 0.0)

    return {
        "probe_error": None,
        "container": str(fmt.get("format_name", "unknown")),
        "codec": str(vstream.get("codec_name", "unknown")),
        "width": int(vstream.get("width", 0)),
        "height": int(vstream.get("height", 0)),
        "rotation": rotation,
        "display_width": display_w,
        "display_height": display_h,
        "r_frame_rate": str(vstream.get("r_frame_rate", "0/1")),
        "avg_frame_rate": str(vstream.get("avg_frame_rate", "0/1")),
        "r_fps_val": _parse_fps(str(vstream.get("r_frame_rate") or "0/1")),
        "avg_fps_val": _parse_fps(str(vstream.get("avg_frame_rate") or "0/1")),
        "vfr_suspected": vfr_suspected,
        "nb_frames": str(vstream.get("nb_frames", "N/A")),
        "duration_sec": dur,
        "creation_time_raw": str(raw_ct) if raw_ct else "N/A",
        "creation_time_ist": _ist_from_creation_time(str(raw_ct) if raw_ct else None),
        "audio_present": audio_present,
    }


def _normalise_command(src_path: Path, norm_path: Path) -> list[str]:
    """Build deterministic CFR H.264 normalisation ffmpeg command."""
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(src_path),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-fps_mode",
        "cfr",
        str(norm_path),
    ]


def _check_readability(clip_path: Path, duration_sec: float) -> tuple[bool, str]:
    """Try reading up to 5 frames via pipeline.frames.iter_sampled_frames."""
    try:
        end_t = max(1.0, min(duration_sec, 10.0)) if duration_sec > 0 else 5.0
        frames = list(iter_sampled_frames(clip_path, 0.0, end_t, sample_fps=2.0, max_frames=5))
        if not frames:
            return False, "0 frames decoded by pipeline.frames"
        for _, fr in frames:
            if fr is None or getattr(fr, "size", 0) == 0:
                return False, "Empty frame decoded"
        return True, f"OK ({len(frames)} frames)"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _check_timestamp_drift(clip_path: Path, duration_sec: float, search_sec: float = 3.0) -> dict[str, Any]:
    """Measure timestamp drift vs ffmpeg at 10%, 50%, and 90% of clip duration."""
    if duration_sec <= 0.1:
        return {"status": "N/A", "max_abs_offset": None, "details": [], "flagged": False}

    fracs = [0.10, 0.50, 0.90]
    times = [max(0.0, min(duration_sec - 0.05, duration_sec * frac)) for frac in fracs]
    rows = measure_drift(clip_path, times, search_sec=search_sec)
    details = [
        {
            "pct": int(frac * 100),
            "target_t": round(float(row["t_sec"]), 2),
            "offset": row["best_offset"],
            "mad": round(float(row["best_mad"]), 2) if row["best_mad"] is not None else None,
        }
        for frac, row in zip(fracs, rows)
    ]

    valid_offs = [float(d["offset"]) for d in details if d["offset"] is not None]
    if not valid_offs:
        return {"status": "N/A", "max_abs_offset": None, "details": details, "flagged": False}

    worst_off = max(valid_offs, key=abs)
    max_abs = abs(float(worst_off))
    flagged = max_abs > 0.25
    status = f"{worst_off:+.2f}s" + (" (DRIFT)" if flagged else " (OK)")
    return {"status": status, "max_abs_offset": max_abs, "worst_offset": float(worst_off), "details": details, "flagged": flagged}


def _sample_evenly(clip_path: Path, duration_sec: float, target_n: int = 20) -> list[tuple[float, Any]]:
    """Sample up to target_n evenly spaced frames across the clip."""
    if duration_sec <= 0.1:
        return list(iter_sampled_frames(clip_path, 0.0, 10.0, sample_fps=2.0, max_frames=target_n))
    fps = max(0.05, float(target_n - 1) / max(duration_sec, 0.25))
    return list(iter_sampled_frames(clip_path, 0.0, duration_sec, sample_fps=fps, max_frames=target_n))


def _analyze_frames_camera_and_quality(samples: list[tuple[float, Any]]) -> dict[str, Any]:
    """Estimate fixed/moving camera heuristic (border MAD vs temporal median) and light/sharpness stats."""
    import cv2
    import numpy as np

    if not samples:
        return {
            "camera_label": "N/A (heuristic)",
            "camera_moving": False,
            "border_mad": None,
            "lum": None,
            "sharp": None,
            "dark_flag": False,
            "blur_flag": False,
        }

    border_mask = np.zeros((90, 160), dtype=bool)
    border_mask[:11, :] = True
    border_mask[-11:, :] = True
    border_mask[:, :19] = True
    border_mask[:, -19:] = True

    lums: list[float] = []
    sharps: list[float] = []
    small_grays: list[Any] = []

    for _, frame in samples:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        lums.append(float(np.mean(gray)))
        sharps.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
        small = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA).astype(np.float32)
        small_grays.append(small)

    lum_stats = (round(min(lums), 1), round(float(np.median(lums)), 1), round(max(lums), 1))
    sharp_stats = (round(min(sharps), 1), round(float(np.median(sharps)), 1), round(max(sharps), 1))

    if len(small_grays) < 3:
        border_mad = 0.0
        cam_moving = False
        cam_label = f"unknown ({len(small_grays)} frames, heuristic)"
    else:
        stack = np.stack(small_grays, axis=0)
        med = np.median(stack, axis=0)
        frame_border_mads = [float(np.mean(np.abs(g[border_mask] - med[border_mask]))) for g in small_grays]
        border_mad = round(float(np.median(frame_border_mads)), 2)
        cam_moving = border_mad > 8.0
        tag = "likely moving" if cam_moving else "likely fixed"
        cam_label = f"{tag} (border_mad={border_mad:.1f}, heuristic)"

    return {
        "camera_label": cam_label,
        "camera_moving": cam_moving,
        "border_mad": border_mad,
        "lum": lum_stats,
        "sharp": sharp_stats,
        "dark_flag": lum_stats[1] < 45.0,
        "blur_flag": sharp_stats[1] < 30.0,
    }


def _save_contact_sheet(samples: list[tuple[float, Any]], out_path: Path, cols: int = 4, rows: int = 3) -> Path | None:
    """Save a 12-tile (4x3) timestamped contact sheet under out_path."""
    import cv2
    import numpy as np

    if not samples:
        return None

    total = cols * rows
    if len(samples) <= total:
        picked = list(samples)
    else:
        idxs = [int(round(i * (len(samples) - 1) / float(total - 1))) for i in range(total)]
        picked = [samples[i] for i in idxs]

    tw, th = 320, 180
    sheet = np.zeros((rows * th, cols * tw, 3), dtype=np.uint8)
    for tile_idx, (ts, frame) in enumerate(picked):
        r, c = divmod(tile_idx, cols)
        fh, fw = frame.shape[:2]
        scale = min(tw / max(1, fw), th / max(1, fh))
        nw = max(1, int(round(fw * scale)))
        nh = max(1, int(round(fh * scale)))
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)

        tile = np.zeros((th, tw, 3), dtype=np.uint8)
        y0 = (th - nh) // 2
        x0 = (tw - nw) // 2
        tile[y0 : y0 + nh, x0 : x0 + nw] = resized
        cv2.rectangle(tile, (4, 4), (108, 26), (0, 0, 0), -1)
        cv2.putText(tile, f"t={ts:.2f}s", (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        sheet[r * th : (r + 1) * th, c * tw : (c + 1) * tw] = tile

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), sheet)
    return out_path


def _sanitize_id(stem: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in stem).strip("_") or "clip"


def onboard_folder(
    folder: str | Path,
    out_dir: str | Path = Path("data/outputs/onboarding"),
    convert: bool = False,
    normalised_dir: str | Path = Path("data/samples/normalised"),
) -> dict[str, Any]:
    """Run onboarding diagnostics on every file in folder and write draft manifest + report."""
    src_folder = Path(folder)
    if not src_folder.is_dir():
        raise FileNotFoundError(f"Input folder not found: {src_folder}")

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    sheets_dir = out_path / "contact_sheets"
    norm_dir = Path(normalised_dir)

    all_files = sorted(p for p in src_folder.iterdir() if p.is_file())
    video_files = [p for p in all_files if p.suffix.lower() in VIDEO_EXTENSIONS]
    non_video_files = [p for p in all_files if p.suffix.lower() not in VIDEO_EXTENSIONS]

    records: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, str]] = []
    problems: list[str] = []

    for clip_path in video_files:
        probe = _probe_clip(clip_path)
        notes_list: list[str] = []
        active_clip = clip_path
        converted_path: Path | None = None

        if probe.get("probe_error"):
            err_msg = str(probe["probe_error"])
            problems.append(f"`{clip_path.name}`: ffprobe failed ({err_msg})")
            norm_target = norm_dir / f"{clip_path.stem}.mp4"
            ff_cmd = _normalise_command(clip_path, norm_target)
            print(f"[onboard] Unreadable clip {clip_path.name}; normalise with:\n  {shlex.join(ff_cmd)}")
            if convert:
                norm_dir.mkdir(parents=True, exist_ok=True)
                conv_proc = subprocess.run(ff_cmd, capture_output=True, text=True)
                if conv_proc.returncode == 0 and norm_target.exists():
                    converted_path = norm_target
                    active_clip = norm_target
                    probe = _probe_clip(active_clip)
                    notes_list.append(f"converted -> {norm_target}")
                else:
                    notes_list.append(f"convert failed (rc={conv_proc.returncode})")
                    problems.append(f"`{clip_path.name}`: ffmpeg --convert failed")
            else:
                notes_list.append("ffprobe error; see normalise cmd")

        dur = float(probe.get("duration_sec", 0.0) or 0.0)
        if probe.get("probe_error"):
            readable_ok, readable_msg = False, str(probe["probe_error"])
        else:
            readable_ok, readable_msg = _check_readability(active_clip, dur)
            if not readable_ok:
                problems.append(f"`{clip_path.name}`: unreadable ({readable_msg})")
                norm_target = norm_dir / f"{clip_path.stem}.mp4"
                ff_cmd = _normalise_command(clip_path, norm_target)
                print(f"[onboard] Unreadable clip {clip_path.name}; normalise with:\n  {shlex.join(ff_cmd)}")
                if convert and converted_path is None:
                    norm_dir.mkdir(parents=True, exist_ok=True)
                    conv_proc = subprocess.run(ff_cmd, capture_output=True, text=True)
                    if conv_proc.returncode == 0 and norm_target.exists():
                        converted_path = norm_target
                        active_clip = norm_target
                        probe = _probe_clip(active_clip)
                        dur = float(probe.get("duration_sec", 0.0) or 0.0)
                        readable_ok, readable_msg = _check_readability(active_clip, dur)
                        notes_list.append(f"converted -> {norm_target} ({readable_msg})")
                        if not readable_ok:
                            problems.append(f"`{clip_path.name}`: still unreadable after convert ({readable_msg})")
                    else:
                        notes_list.append(f"convert failed (rc={conv_proc.returncode})")
                        problems.append(f"`{clip_path.name}`: ffmpeg --convert failed")
                else:
                    notes_list.append("unreadable; run with --convert")

        if probe.get("vfr_suspected"):
            notes_list.append("VFR suspected")
            problems.append(
                f"`{clip_path.name}`: variable frame rate suspected (r={probe.get('r_frame_rate')}, avg={probe.get('avg_frame_rate')})"
            )
        if int(probe.get("rotation", 0) or 0) != 0:
            notes_list.append(f"rot={probe['rotation']}deg")

        drift_info: dict[str, Any] = {"status": "N/A", "flagged": False, "details": []}
        cam_light: dict[str, Any] = {
            "camera_label": "N/A (heuristic)",
            "lum": None,
            "sharp": None,
            "dark_flag": False,
            "blur_flag": False,
        }
        contact_path: Path | None = None

        if readable_ok:
            drift_info = _check_timestamp_drift(active_clip, dur)
            if drift_info["flagged"]:
                problems.append(f"`{clip_path.name}`: timestamp drift {drift_info['status']}")

            samples = _sample_evenly(active_clip, dur, target_n=20)
            cam_light = _analyze_frames_camera_and_quality(samples)
            if cam_light["camera_moving"]:
                problems.append(f"`{clip_path.name}`: camera {cam_light['camera_label']}")
            if cam_light["dark_flag"]:
                problems.append(f"`{clip_path.name}`: dark median luminance ({cam_light['lum'][1]})")
            if cam_light["blur_flag"]:
                problems.append(f"`{clip_path.name}`: low median sharpness ({cam_light['sharp'][1]})")

            contact_path = _save_contact_sheet(samples, sheets_dir / f"{clip_path.stem}_contact.jpg")

        fps_str = (
            f"{probe.get('r_fps_val', 0):.2f} / {probe.get('avg_fps_val', 0):.2f}"
            if not probe.get("probe_error")
            else "N/A"
        )
        res_str = (
            f"{probe['display_width']}x{probe['display_height']}"
            if not probe.get("probe_error")
            else "N/A"
        )
        light_str = (
            f"{cam_light['lum'][0]}/{cam_light['lum'][1]}/{cam_light['lum'][2]}"
            if cam_light["lum"] is not None
            else "N/A"
        )

        records.append(
            {
                "clip_name": clip_path.name,
                "clip_path": str(active_clip),
                "probe": probe,
                "fps_str": fps_str,
                "res_str": res_str,
                "duration_str": f"{dur:.2f}s" if not probe.get("probe_error") else "N/A",
                "readable": readable_msg,
                "drift": drift_info["status"],
                "camera": cam_light["camera_label"],
                "light": light_str,
                "sharp": cam_light["sharp"],
                "notes": "; ".join(notes_list) if notes_list else "-",
                "contact_sheet": str(contact_path) if contact_path else None,
            }
        )

        manifest_rows.append(
            {
                "case_id": _sanitize_id(clip_path.stem),
                "clip": str(active_clip),
                "atm_id": f"cam_{clip_path.stem}",
                "tx_sec": "",
                "window_sec": "10",
                "expect_link": "",
                "gt_intervals": "",
                "manual_best_t": "",
                "expect_frontal": "",
                "notes": "TO FILL BY HUMAN",
            }
        )

    manifest_draft_path = out_path / "manifest_draft.csv"
    with manifest_draft_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(manifest_rows)

    report_lines = [
        "# Clip Onboarding Report",
        "",
        f"Source folder: `{src_folder}` | Video files: {len(video_files)} | Non-video files: {len(non_video_files)}",
        f"Draft manifest: `{manifest_draft_path}`",
        "",
        "## Summary",
        "",
        "| clip | container | codec | resolution | fps r/avg | duration | readable | drift | camera | light | notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for rec in records:
        p = rec["probe"]
        report_lines.append(
            f"| `{rec['clip_name']}` | {p.get('container', 'N/A')} | {p.get('codec', 'N/A')} | "
            f"{rec['res_str']} | {rec['fps_str']} | {rec['duration_str']} | "
            f"{rec['readable']} | {rec['drift']} | {rec['camera']} | {rec['light']} | {rec['notes']} |"
        )

    report_lines.extend(["", "## Problems", ""])
    if problems:
        for item in problems:
            report_lines.append(f"- {item}")
    else:
        report_lines.append("- None")

    report_lines.extend(["", "## Non-video Files", ""])
    if non_video_files:
        for nv in non_video_files:
            report_lines.append(f"- `{nv.name}` ({nv.stat().st_size} bytes)")
    else:
        report_lines.append("- None")

    report_lines.extend(["", "## Detailed Clip Metadata", ""])
    for rec in records:
        p = rec["probe"]
        sh_str = (
            f"{rec['sharp'][0]}/{rec['sharp'][1]}/{rec['sharp'][2]}"
            if rec["sharp"] is not None
            else "N/A"
        )
        report_lines.append(f"### `{rec['clip_name']}`")
        report_lines.append(f"- Coded: {p.get('width', 'N/A')}x{p.get('height', 'N/A')}, rotation: {p.get('rotation', 'N/A')} deg, display: {rec['res_str']}")
        report_lines.append(f"- r_frame_rate={p.get('r_frame_rate', 'N/A')}, avg_frame_rate={p.get('avg_frame_rate', 'N/A')}, vfr_suspected={p.get('vfr_suspected', 'N/A')}, nb_frames={p.get('nb_frames', 'N/A')}")
        report_lines.append(f"- creation_time (raw): `{p.get('creation_time_raw', 'N/A')}` | Asia/Kolkata: `{p.get('creation_time_ist', 'N/A')}` | audio: `{p.get('audio_present', 'N/A')}`")
        report_lines.append(f"- luminance min/med/max: `{rec['light']}` | sharpness (Laplacian var) min/med/max: `{sh_str}`")
        if rec["contact_sheet"]:
            report_lines.append(f"- contact_sheet (local out only): `{rec['contact_sheet']}`")
        report_lines.append("")

    report_text = "\n".join(report_lines)
    report_path = out_path / "onboarding_report.md"
    report_path.write_text(report_text, encoding="utf-8")

    return {
        "records": records,
        "problems": problems,
        "non_video_files": [p.name for p in non_video_files],
        "report_path": str(report_path),
        "manifest_draft_path": str(manifest_draft_path),
        "report_text": report_text,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect and onboard organiser video clips.")
    parser.add_argument("folder", type=Path, help="Folder containing video clips")
    parser.add_argument("--out", type=Path, default=Path("data/outputs/onboarding"), help="Output directory")
    parser.add_argument("--convert", action="store_true", help="Convert unreadable clips to CFR H.264 under data/samples/normalised/")
    args = parser.parse_args()

    out = onboard_folder(args.folder, out_dir=args.out, convert=args.convert)

    print("\n## Summary\n")
    in_summary = False
    for line in out["report_text"].splitlines():
        if line.startswith("| clip |") or (in_summary and line.startswith("|")):
            in_summary = True
            print(line)
        elif in_summary:
            break

    print("\n## Problems\n")
    if out["problems"]:
        for p in out["problems"]:
            print(f"- {p}")
    else:
        print("- None")

    print(f"\nSaved report: {out['report_path']}")
    print(f"Saved draft manifest: {out['manifest_draft_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
