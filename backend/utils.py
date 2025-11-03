import os
import uuid
from pathlib import Path
from dotenv import load_dotenv


load_dotenv()


DATA_DIR = Path(os.getenv("DATA_DIR", "./data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)




def new_video_id() -> str:
return uuid.uuid4().hex[:12]




def ensure_dir(path: Path) -> Path:
path.mkdir(parents=True, exist_ok=True)
return path




def sec_to_tc(seconds: float) -> str:
# naar HH:MM:SS.ms
ms = int((seconds - int(seconds)) * 1000)
s = int(seconds) % 60
m = (int(seconds) // 60) % 60
h = int(seconds) // 3600
return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"