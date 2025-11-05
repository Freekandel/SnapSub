import math
import subprocess
from pathlib import Path
from typing import List, Optional

import ffmpeg


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


def pick_times(total: float, n_clips: int) -> List[float]:
    """Kies n_clips tijdstippen gelijkmatig over de video."""
    if n_clips <= 0 or total <= 0:
        return []
    step = total / (n_clips + 1)
    return [step * (i + 1) for i in range(n_clips)]


def export_clip(
    input_path: Path,
    out_dir: Path,
    start: float,
    end: float,
    index: int,
) -> Path:
    """Exporteer een simpele clip zonder ingewikkelde filters."""
    duration = max(0.1, end - start)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"clip_{index+1}.mp4"

    # Heel simpele ffmpeg-call: knip een stukje uit en zet om naar H.264 + AAC
    stream = ffmpeg.input(str(input_path), ss=start, t=duration)
    out = ffmpeg.output(
        stream,
        str(out_path),
        vcodec="libx264",
        acodec="aac",
        pix_fmt="yuv420p",
        movflags="+faststart",
    ).overwrite_output()

    try:
        out.run(quiet=True)
    except ffmpeg.Error as e:
        # Log naar stdout zodat het zichtbaar wordt in Render-logs
        print("FFmpeg error:", e)
        raise

    return out_path


def generate_clips(
    input_path: Path,
    out_dir: Path,
    n_clips: int = 3,
    clip_len: int = 20,
    scene_thresh: float = 0.3,  # niet meer gebruikt, maar laten staan voor compat
    srt_path: Optional[Path] = None,  # niet gebruikt
    branding_png: Optional[Path] = None,  # niet gebruikt
) -> List[Path]:
    """
    Simpele implementatie:
    - meet totale lengte
    - kies n_clips tijdstippen gelijkmatig verdeeld
    - knip per tijdstip een venster van clip_len seconden
    """
    total = probe_duration(input_path)
    times = pick_times(total, n_clips)

    half = clip_len / 2
    spans = []
    for t in times:
        start = max(0.0, t - half)
        end = min(total, t + half)
        if end - start <= 0:
            continue
        spans.append((start, end))

    outputs: List[Path] = []
    for idx, (s, e) in enumerate(spans):
        outp = export_clip(
            input_path=input_path,
            out_dir=out_dir,
            start=s,
            end=e,
            index=idx,
        )
        outputs.append(outp)

    return outputs
