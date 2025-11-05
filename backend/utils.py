import os
import uuid
from pathlib import Path

# Basisdirectory voor data
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))

def ensure_dir(p: Path) -> Path:
    """Zorgt dat een map bestaat en retourneert het pad."""
    p.mkdir(parents=True, exist_ok=True)
    return p

def new_video_id() -> str:
    """Genereert een korte unieke ID voor een video."""
    return uuid.uuid4().hex[:12]

def sec_to_tc(sec: float) -> str:
    """Converteer seconden naar tijdcode (hh:mm:ss)."""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"