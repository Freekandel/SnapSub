import math
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional

import ffmpeg

from .utils import sec_to_tc


def probe_duration(input_path: Path) -> float:
    """Return video duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(input_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def detect_scenes(input_path: Path, threshold: float = 0.3) -> List[float]:
    """Detecteer scènewisselingen (timestamps in seconden) met ffmpeg scene filter."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(input_path),
        "-vf",
        f"select='gt(scene,{threshold})',showinfo",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    lines = proc.stderr.splitlines()
    pts_times = []
    for ln in lines:
        if "showinfo" in ln and "pts_time:" in ln:
            try:
                part = ln.split("pts_time:")[-1]
                t = float(part.split(" ")[0])
                pts_times.append(t)
            except Exception:
                pass
    return sorted(set(round(t, 3) for t in pts_times))


def window_around(t: float, half: float, total: float) -> Tuple[float, float]:
    start = max(0.0, t - half)
    end = min(total, t + half)
    # fix: zorg minimaal 3 seconden
    if end - start < 3:
        end = min(total, start + 3)
    return (start, end)


def unique_non_overlapping(
    spans: List[Tuple[float, float]], min_gap: float = 2.0
) -> List[Tuple[float, float]]:
    spans = sorted(spans)
    out: List[Tuple[float, float]] = []
    for s, e in spans:
        if not out:
            out.append((s, e))
        else:
            ps, pe = out[-1]
            if s - pe >= min_gap:
                out.append((s, e))
            else:
                # merge conservatief
                out[-1] = (ps, max(pe, e))
    return out


def crop_aspect_filter(target: str) -> str:
    """FFmpeg crop+scale chain voor target aspect: '9:16' | '1:1' | '16:9'"""
    if target == "9:16":
        # center-crop portrait, daarna scale naar 1080x1920
        return "crop='in_h*9/16:in_h:(in_w-out_w)/2:0',scale=1080:1920"
    if target == "1:1":
        return "crop='min(in_w,in_h):min(in_w,in_h)',scale=1080:1080"
    # default 16:9 naar 1920x1080
    return (
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
    )


def burn_subtitles_if_any(input_path: Path, srt_path: Optional[Path]) -> str:
    if srt_path and srt_path.exists():
        # ffmpeg subtitles filter
        return f"subtitles='{srt_path.as_posix()}'"
    return "null"


def export_clip(
    input_path: Path,
    out_dir: Path,
    start: float,
    end: float,
    aspect: str = "9:16",
    srt_path: Optional[Path] = None,
    branding_png: Optional[Path] = None,
) -> Path:
    duration = max(0.1, end - start)
    vf_chain = [
        crop_aspect_filter(aspect),
    ]

    # subtitles als apart filtergraph (optioneel)
    sub_filter = burn_subtitles_if_any(input_path, srt_path)

    vf = ",".join([f for f in vf_chain if f])

    out_path = out_dir / f"clip_{sec_to_tc(start).replace(':', '-')}_{aspect.replace(':', 'x')}.mp4"

    input_stream = ffmpeg.input(str(input_path), ss=start, t=duration)
    video = input_stream.video
    audio = input_stream.audio

    # Subtitles filter
    if sub_filter != "null":
        video = video.filter_("subtitles", str(srt_path))

    # Aspect chain
    for f in vf.split(","):
        name, *args = f.split("=")
        if args:
            video = video.filter_(name, args[0])
        else:
            video = video.filter_(name)

    # Overlay branding (optioneel)
    if branding_png and branding_png.exists():
        logo = ffmpeg.input(str(branding_png))
        video = ffmpeg.overlay(
            video,
            logo,
            x="(main_w-overlay_w-40)",
            y="(main_h-overlay_h-40)",
        )

    out = ffmpeg.output(
        video,
        audio,
        str(out_path),
        vcodec="h264",
        acodec="aac",
        pix_fmt="yuv420p",
        movflags="+faststart",
    ).overwrite_output()

    out.run(quiet=True)
    return out_path


def generate_clips(
    input_path: Path,
    out_dir: Path,
    n_clips: int = 3,
    clip_len: int = 20,
    scene_thresh: float = 0.3,
    srt_path: Optional[Path] = None,
    branding_png: Optional[Path] = None,
) -> List[Path]:
    total = probe_duration(input_path)
    scene_times = detect_scenes(input_path, threshold=scene_thresh)

    if not scene_times:
        # fallback: verdeel gelijkmatig
        step = total / (n_clips + 1)
        scene_times = [step * (i + 1) for i in range(n_clips)]

    # kies top-N gelijkmatig verdeeld uit scene_times
    if len(scene_times) > n_clips:
        stride = max(1, math.floor(len(scene_times) / n_clips))
        picks = scene_times[::stride][:n_clips]
    else:
        picks = scene_times[:n_clips]

    half = clip_len / 2
    spans = [window_around(t, half=half, total=total) for t in picks]
    spans = unique_non_overlapping(spans)

    outputs: List[Path] = []
    for (s, e) in spans:
        for aspect in ("9:16", "1:1", "16:9"):
            outp = export_clip(
                input_path=input_path,
                out_dir=out_dir,
                start=s,
                end=e,
                aspect=aspect,
                srt_path=srt_path,
                branding_png=branding_png,
            )
            outputs.append(outp)
    return outputs
