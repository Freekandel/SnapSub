from __future__ import annotations

import json
import logging
import random
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import ffmpeg

logger = logging.getLogger(__name__)


class ClipStrategy(str, Enum):
    EVEN = "even"
    SCENE = "scene"
    RANDOM = "random"


@dataclass
class ExportOptions:
    codec: str = "libx264"
    crf: int = 18
    preset: str = "medium"
    audio_bitrate: str = "160k"
    add_fade: bool = True
    fade_duration: float = 0.6
    target_resolution: Optional[Tuple[int, int]] = None
    maintain_aspect: bool = True
    fps: Optional[int] = None
    gif_preview: bool = False
    gif_scale: int = 512
    gif_fps: int = 12


@dataclass
class ClipMetadata:
    index: int
    start: float
    end: float
    duration: float
    video_path: Path
    gif_preview: Optional[Path] = None


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


def _detect_keyframe_scenes(
    input_path: Path,
    min_gap: float,
    limit: int | None = None,
) -> List[float]:
    """
    Use ffprobe to list keyframe timestamps, filter them by min_gap (seconds)
    as a lightweight proxy for scene-change detection.
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-skip_frame",
        "nokey",
        "-show_entries",
        "frame=pkt_pts_time",
        "-of",
        "json",
        str(input_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(proc.stdout or "{}")
    frames = data.get("frames", [])

    picks: List[float] = []
    last_time = -float("inf")
    for frame in frames:
        try:
            t = float(frame["pkt_pts_time"])
        except (KeyError, ValueError, TypeError):
            continue
        if t - last_time >= min_gap:
            picks.append(t)
            last_time = t
            if limit and len(picks) >= limit:
                break
    return picks


def _pick_times(
    total: float,
    n_clips: int,
    clip_len: float,
    strategy: ClipStrategy,
    scene_candidates: Sequence[float],
) -> List[float]:
    half = clip_len / 2
    safe_min = half
    safe_max = max(half, total - half)

    if strategy == ClipStrategy.SCENE and scene_candidates:
        centers = [min(max(t, safe_min), safe_max) for t in scene_candidates]
        if len(centers) >= n_clips:
            return centers[:n_clips]
        remaining = n_clips - len(centers)
        return centers + _pick_times(total, remaining, clip_len, ClipStrategy.EVEN, [])

    if strategy == ClipStrategy.RANDOM:
        return [
            random.uniform(safe_min, safe_max) if total > clip_len else total / 2
            for _ in range(n_clips)
        ]

    step = total / (n_clips + 1)
    return [min(max(step * (i + 1), safe_min), safe_max) for i in range(n_clips)]


def _window_for_center(center: float, clip_len: float, total: float) -> Tuple[float, float]:
    half = clip_len / 2
    start = center - half
    end = center + half
    if start < 0:
        end = min(total, end - start)
        start = 0.0
    if end > total:
        shift = end - total
        start = max(0.0, start - shift)
        end = total
    if end - start < 0.1:
        end = min(total, start + 0.1)
    return round(start, 3), round(end, 3)


def _apply_video_filters(
    video_stream,
    duration: float,
    export_opts: ExportOptions,
    srt_path: Optional[Path],
):
    if export_opts.target_resolution:
        w, h = export_opts.target_resolution
        video_stream = video_stream.filter(
            "scale",
            f"{w}:{h}",
            f"force_original_aspect_ratio={'decrease' if export_opts.maintain_aspect else 'disable'}",
        )
        if export_opts.maintain_aspect:
            video_stream = video_stream.filter(
                "pad",
                w,
                h,
                "(ow-iw)/2",
                "(oh-ih)/2",
                "black",
            )
    if export_opts.fps:
        video_stream = video_stream.filter("fps", export_opts.fps)
    if export_opts.add_fade and duration > 2 * export_opts.fade_duration:
        video_stream = video_stream.filter(
            "fade",
            "t=in",
            "st=0",
            f"d={export_opts.fade_duration}",
        ).filter(
            "fade",
            "t=out",
            f"st={duration - export_opts.fade_duration}",
            f"d={export_opts.fade_duration}",
        )
    if srt_path:
        video_stream = video_stream.filter_("subtitles", str(srt_path))
    return video_stream


def _apply_watermark(video_stream, branding_png: Path, scale: float, position: str):
    if not branding_png.exists():
        logger.warning("Branding PNG %s not found; skipping overlay.", branding_png)
        return video_stream

    logo = (
        ffmpeg.input(str(branding_png))
        .filter("scale", f"iw*{scale}", -1)
        .filter("format", "rgba")
    )

    positions = {
        "top-left": ("24", "24"),
        "top-right": ("main_w-overlay_w-24", "24"),
        "bottom-left": ("24", "main_h-overlay_h-24"),
        "bottom-right": ("main_w-overlay_w-24", "main_h-overlay_h-24"),
        "center": ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
    }
    x, y = positions.get(position.lower(), positions["bottom-right"])
    return ffmpeg.overlay(video_stream, logo, x=x, y=y)


def _export_gif_preview(
    clip_path: Path,
    gif_path: Path,
    export_opts: ExportOptions,
):
    src = ffmpeg.input(str(clip_path))
    palette = (
        src.filter("fps", export_opts.gif_fps)
        .filter("scale", export_opts.gif_scale, -1)
        .filter("palettegen")
    )
    stream = (
        ffmpeg.input(str(clip_path))
        .filter("fps", export_opts.gif_fps)
        .filter("scale", export_opts.gif_scale, -1)
    )
    gif = ffmpeg.output(
        stream,
        palette,
        str(gif_path),
        loop=0,
        format="gif",
    ).overwrite_output()

    try:
        gif.run(capture_stdout=True, capture_stderr=True)
        return gif_path
    except ffmpeg.Error as exc:
        stderr = exc.stderr.decode("utf-8", "ignore") if exc.stderr else "No stderr"
        logger.warning("Failed to build GIF preview: %s", stderr)
        return None


def generate_clips(
    input_path: Path,
    out_dir: Path,
    n_clips: int = 3,
    clip_len: int = 20,
    scene_thresh: float = 0.3,
    srt_path: Optional[Path] = None,
    branding_png: Optional[Path] = None,
    *,
    strategy: ClipStrategy = ClipStrategy.EVEN,
    branding_position: str = "bottom-right",
    branding_scale: float = 0.22,
    export_opts: Optional[ExportOptions] = None,
) -> List[ClipMetadata]:
    """
    Fancy multi-clip exporter.
    """
    export_opts = export_opts or ExportOptions()
    total = probe_duration(input_path)

    min_gap = max(1.0, clip_len * (1 - scene_thresh))
    scene_candidates = _detect_keyframe_scenes(input_path, min_gap, limit=n_clips * 2)
    centers = _pick_times(total, n_clips, clip_len, strategy, scene_candidates)

    spans = [
        _window_for_center(center, clip_len, total)
        for center in centers
        if total > 0 and clip_len > 0
    ]

    outputs: List[ClipMetadata] = []
    for idx, (start, end) in enumerate(spans, start=1):
        duration = end - start
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"clip_{idx:02d}.mp4"

        stream = ffmpeg.input(str(input_path), ss=start, t=duration)
        video = _apply_video_filters(stream.video, duration, export_opts, srt_path)

        if branding_png:
            video = _apply_watermark(video, branding_png, branding_scale, branding_position)

        audio = stream.audio

        out = (
            ffmpeg.output(
                video,
                audio,
                str(out_path),
                vcodec=export_opts.codec,
                crf=export_opts.crf,
                preset=export_opts.preset,
                acodec="aac",
                audio_bitrate=export_opts.audio_bitrate,
                pix_fmt="yuv420p",
                movflags="+faststart",
            )
            .overwrite_output()
        )

        try:
            out.run(capture_stdout=True, capture_stderr=True)
        except ffmpeg.Error as exc:
            stderr = exc.stderr.decode("utf-8", "ignore") if exc.stderr else "No stderr"
            logger.error("FFmpeg failed on clip %s:\n%s", idx, stderr)
            continue

        gif_path = None
        if export_opts.gif_preview:
            gif_path = _export_gif_preview(
                out_path,
                out_path.with_suffix(".gif"),
                export_opts,
            )

        outputs.append(
            ClipMetadata(
                index=idx,
                start=start,
                end=end,
                duration=duration,
                video_path=out_path,
                gif_preview=gif_path,
            )
        )

    return outputs