#!/usr/bin/env python3
"""Assemble YYYYMMDD.png daylight frames into an MP4 (or WebM) video via ffmpeg.

Uses ffmpeg's concat demuxer, which works correctly on Windows, macOS, and
Linux regardless of how the files are named — no glob patterns needed.

Examples
--------
All frames in viz/frames/ → viz/daylight.mp4 at 30 fps:
    python viz/make_video.py

Just the year 2026:
    python viz/make_video.py --year 2026

A summer date range:
    python viz/make_video.py --start 2026-06-01 --end 2026-08-31

Slower playback (12 fps), higher quality:
    python viz/make_video.py --fps 12 --crf 16

Custom input/output paths:
    python viz/make_video.py --frames viz/frames/alaska --out viz/alaska_2026.mp4

H.265 (smaller file, same quality):
    python viz/make_video.py --codec h265

Requirements
------------
ffmpeg must be installed and on your PATH:
    Windows:  winget install ffmpeg      (or https://ffmpeg.org/download.html)
    Mac:      brew install ffmpeg
    Linux:    sudo apt install ffmpeg
"""

import argparse
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assemble daylight frame PNGs into a video using ffmpeg.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--frames",
        default="viz/frames/",
        metavar="DIR",
        help="Directory containing YYYYMMDD.png frame files (default: viz/frames/).",
    )
    parser.add_argument(
        "--out",
        default=None,
        metavar="FILE",
        help=(
            "Output video file (default: viz/daylight.mp4, or "
            "viz/daylight_YYYY.mp4 when --year is given, etc.)."
        ),
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=30,
        metavar="N",
        help="Playback frame rate in frames-per-second (default: 30).",
    )

    # --- Date filter (optional, mutually exclusive) ---
    filter_group = parser.add_mutually_exclusive_group()
    filter_group.add_argument(
        "--year",
        type=int,
        metavar="YYYY",
        help="Include only frames from this calendar year.",
    )
    filter_group.add_argument(
        "--start",
        metavar="YYYY-MM-DD",
        help="Include frames from this date onward (requires --end).",
    )
    parser.add_argument(
        "--end",
        metavar="YYYY-MM-DD",
        help="Include frames up to this date (requires --start).",
    )

    # --- Encoding ---
    parser.add_argument(
        "--crf",
        type=int,
        default=18,
        metavar="N",
        help=(
            "Quality factor for h264/h265 (0=lossless … 51=worst; "
            "default: 18).  For vp9 the scale is 0–63."
        ),
    )
    parser.add_argument(
        "--codec",
        choices=["h264", "h265", "vp9"],
        default="h264",
        help="Video codec (default: h264 — widest compatibility).",
    )
    parser.add_argument(
        "--preset",
        choices=["ultrafast", "fast", "medium", "slow", "veryslow"],
        default="slow",
        help="Encoding speed/compression trade-off for h264/h265 (default: slow).",
    )

    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Frame discovery
# ---------------------------------------------------------------------------

def collect_frames(
    frames_dir: Path,
    year: int | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[Path]:
    """Return sorted list of YYYYMMDD.png files matching the date filter."""
    # Match exactly 8-digit stems (YYYYMMDD) with .png extension
    all_frames = sorted(
        f for f in frames_dir.glob("????????.png")
        if f.stem.isdigit() and len(f.stem) == 8
    )

    if year is not None:
        year_str = str(year)
        return [f for f in all_frames if f.stem[:4] == year_str]

    if start is not None and end is not None:
        lo = start.strftime("%Y%m%d")
        hi = end.strftime("%Y%m%d")
        return [f for f in all_frames if lo <= f.stem <= hi]

    return all_frames


# ---------------------------------------------------------------------------
# ffmpeg concat list
# ---------------------------------------------------------------------------

def write_concat_list(frames: list[Path], fps: int) -> str:
    """Write an ffmpeg concat demuxer text file; return its path."""
    duration = 1.0 / fps
    lines: list[str] = []
    for f in frames:
        # Use forward-slash paths (required by ffmpeg concat even on Windows)
        lines.append(f"file '{f.resolve().as_posix()}'")
        lines.append(f"duration {duration:.8f}")
    # Repeat the last frame as a sentinel so its duration is respected
    if frames:
        lines.append(f"file '{frames[-1].resolve().as_posix()}'")

    # Write to a temporary file
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    tmp.write("\n".join(lines) + "\n")
    tmp.close()
    return tmp.name


# ---------------------------------------------------------------------------
# ffmpeg invocation
# ---------------------------------------------------------------------------

def build_ffmpeg_cmd(
    concat_file: str,
    out: Path,
    fps: int,
    crf: int,
    codec: str,
    preset: str,
) -> list[str]:
    codec_map = {"h264": "libx264", "h265": "libx265", "vp9": "libvpx-vp9"}
    vcodec = codec_map[codec]

    # H.264/H.265 require width and height divisible by 2.
    # matplotlib's bbox_inches="tight" often produces odd pixel dimensions,
    # so we round each dimension down to the nearest even number.
    scale_filter = "scale=trunc(iw/2)*2:trunc(ih/2)*2"

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-vf", scale_filter,
        "-c:v", vcodec,
        "-pix_fmt", "yuv420p",
        "-crf", str(crf),
        "-r", str(fps),
    ]

    if codec in ("h264", "h265"):
        cmd += ["-preset", preset]
    elif codec == "vp9":
        # vp9 uses -b:v 0 with -crf for constrained quality mode
        cmd += ["-b:v", "0"]

    cmd.append(str(out))
    return cmd


def default_out_name(
    frames_dir: Path,
    year: int | None,
    start: date | None,
    end: date | None,
    codec: str,
) -> Path:
    """Derive a sensible output filename when --out is not specified."""
    ext = ".webm" if codec == "vp9" else ".mp4"
    stem = "daylight"
    if year:
        stem += f"_{year}"
    elif start and end:
        stem += f"_{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"
    # Place next to the frames directory (sibling, not inside)
    return frames_dir.parent / (stem + ext)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None) -> None:
    args = parse_args(argv)

    frames_dir = Path(args.frames)
    if not frames_dir.is_dir():
        print(f"Error: frames directory not found: {frames_dir}", file=sys.stderr)
        sys.exit(1)

    # --- Validate/parse date filter ---
    start_d: date | None = None
    end_d: date | None = None
    if args.start:
        if not args.end:
            print("Error: --start requires --end.", file=sys.stderr)
            sys.exit(1)
        try:
            start_d = date.fromisoformat(args.start)
            end_d = date.fromisoformat(args.end)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        if end_d < start_d:
            print("Error: --end must be on or after --start.", file=sys.stderr)
            sys.exit(1)

    # --- Collect matching frames ---
    frames = collect_frames(frames_dir, year=args.year, start=start_d, end=end_d)
    if not frames:
        msg = "No YYYYMMDD.png frames found"
        if args.year:
            msg += f" for year {args.year}"
        elif start_d:
            msg += f" between {start_d} and {end_d}"
        msg += f" in {frames_dir}"
        print(msg, file=sys.stderr)
        sys.exit(1)

    print(
        f"Found {len(frames)} frame(s):  "
        f"{frames[0].name} \u2192 {frames[-1].name}"
    )

    # --- Resolve output path ---
    if args.out:
        out = Path(args.out)
    else:
        out = default_out_name(frames_dir, args.year, start_d, end_d, args.codec)
    out.parent.mkdir(parents=True, exist_ok=True)

    # --- Duration math ---
    total_seconds = len(frames) / args.fps
    if total_seconds >= 60:
        dur_str = f"{int(total_seconds // 60)}m {int(total_seconds % 60):02d}s"
    else:
        dur_str = f"{total_seconds:.1f}s"
    print(
        f"Output:  {out}\n"
        f"Video:   {args.fps} fps  \u2192  ~{dur_str}  "
        f"codec={args.codec}  crf={args.crf}"
    )

    # --- Build concat list and run ffmpeg ---
    concat_file = write_concat_list(frames, args.fps)
    cmd = build_ffmpeg_cmd(concat_file, out, args.fps, args.crf, args.codec, args.preset)

    print(f"\nRunning ffmpeg ...\n  {' '.join(cmd)}\n")

    try:
        subprocess.run(cmd, check=True)
        print(f"\nDone: {out.resolve()}")
    except FileNotFoundError:
        print(
            "Error: ffmpeg not found.  Install it and ensure it is on your PATH:\n"
            "  Windows:  winget install ffmpeg\n"
            "  Mac:      brew install ffmpeg\n"
            "  Linux:    sudo apt install ffmpeg",
            file=sys.stderr,
        )
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print(f"Error: ffmpeg exited with code {exc.returncode}.", file=sys.stderr)
        sys.exit(1)
    finally:
        Path(concat_file).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
