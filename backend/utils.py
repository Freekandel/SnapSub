from __future__ import annotations

import os
import uuid
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "/data")).resolve()


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists (recursively) and return the path."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_video_id() -> str:
    """Return a short, collision-resistant ID for uploaded videos."""
    return uuid.uuid4().hex[:12]


def sec_to_tc(seconds: float) -> str:
    """Convert seconds to HH:MM:SS timecode."""
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"