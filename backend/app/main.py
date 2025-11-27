from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .clipper import ClipStrategy, ExportOptions, generate_clips
from .utils import DATA_DIR, ensure_dir, new_video_id

load_dotenv()
logger = logging.getLogger(__name__)

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "https://snapsub-frontend.onrender.com")
LOCAL_PREVIEW_ORIGINS = [
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

ALLOWED_ORIGINS = [FRONTEND_ORIGIN, *LOCAL_PREVIEW_ORIGINS]

app = FastAPI(title="SnapSub MVP API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api")


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"service": "SnapSub API", "status": "ok"}


def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


@api.post("/upload")
async def upload_video(
    file: UploadFile | None = File(None),
    source_url: str | None = Form(None),
):
    if not file and not source_url:
        return JSONResponse({"error": "file or source_url required"}, status_code=400)

    vid = new_video_id()
    vid_dir = ensure_dir(DATA_DIR / vid)

    if file:
        in_path = vid_dir / f"input_{file.filename}"
        with open(in_path, "wb") as f:
            f.write(await file.read())
    else:
        if not source_url:
            raise ValueError("source_url must be provided when no file is uploaded")

        tmp_path = vid_dir / "download.mp4"
        subprocess.run(
            ["yt-dlp", "-f", "mp4", "-o", str(tmp_path), source_url],
            check=True,
        )
        in_path = tmp_path

    return {"video_id": vid, "input_path": str(in_path)}


def format_srt_time(t: float) -> str:
    ms = int((t - int(t)) * 1000)
    s = int(t) % 60
    m = (int(t) // 60) % 60
    h = int(t) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


@api.post("/generate")
async def api_generate(
    video_id: str = Form(...),
    n_clips: int = Form(3),
    clip_len: int = Form(20),
    scene_thresh: float = Form(0.3),
    use_whisper: int = Form(0),
    strategy: str = Form("even"),
    branding_name: Optional[str] = Form(None),
    branding_position: str = Form("bottom-right"),
    branding_scale: float = Form(0.22),
    target_width: Optional[int] = Form(None),
    target_height: Optional[int] = Form(None),
    maintain_aspect: int = Form(1),
    fps: Optional[int] = Form(None),
    gif_preview: int = Form(0),
    fade: int = Form(1),
    fade_duration: float = Form(0.6),
):
    vid_dir = DATA_DIR / video_id
    if not vid_dir.exists():
        return JSONResponse({"error": "video_id not found"}, status_code=404)

    inputs = list(vid_dir.glob("input_*"))
    if not inputs:
        return JSONResponse({"error": "no input for video_id"}, status_code=400)
    input_path = inputs[0]

    srt_path: Optional[Path] = None
    if _as_bool(use_whisper):
        try:
            import whisper  # type: ignore

            model = whisper.load_model("small")
            result = model.transcribe(str(input_path))
            srt_path = vid_dir / "subtitles.srt"
            with open(srt_path, "w", encoding="utf-8") as srt:
                for idx, seg in enumerate(result["segments"], start=1):
                    start = seg["start"]
                    end = seg["end"]
                    text = seg["text"].strip()
                    srt.write(f"{idx}\n")
                    srt.write(f"{format_srt_time(start)} --> {format_srt_time(end)}\n")
                    srt.write(text + "\n\n")
        except Exception as exc:  # pragma: no cover
            logger.warning("Whisper transcription failed: %s", exc)

    branding_png: Optional[Path] = None
    if branding_name:
        candidate = vid_dir / branding_name
        if candidate.exists():
            branding_png = candidate
        else:
            logger.warning("Branding asset %s not found; ignoring.", candidate)

    target_resolution = None
    if target_width and target_height:
        target_resolution = (target_width, target_height)

    export_opts = ExportOptions(
        add_fade=_as_bool(fade, True),
        fade_duration=fade_duration,
        target_resolution=target_resolution,
        maintain_aspect=_as_bool(maintain_aspect, True),
        fps=fps,
        gif_preview=_as_bool(gif_preview, False),
    )

    try:
        clip_strategy = ClipStrategy(strategy.lower())
    except ValueError:
        clip_strategy = ClipStrategy.EVEN

    out_dir = ensure_dir(vid_dir / "clips")
    clip_metadata = generate_clips(
        input_path=input_path,
        out_dir=out_dir,
        n_clips=n_clips,
        clip_len=clip_len,
        scene_thresh=scene_thresh,
        srt_path=srt_path,
        branding_png=branding_png,
        strategy=clip_strategy,
        branding_position=branding_position,
        branding_scale=branding_scale,
        export_opts=export_opts,
    )

    base_url = f"/api/download?video_id={video_id}&name="
    clips = [
        {
            "index": meta.index,
            "start": meta.start,
            "end": meta.end,
            "duration": meta.duration,
            "video": f"{base_url}{meta.video_path.name}",
            "gif_preview": f"{base_url}{meta.gif_preview.name}"
            if meta.gif_preview
            else None,
        }
        for meta in clip_metadata
    ]

    return {"video_id": video_id, "clips": clips}


@api.get("/download")
async def download(video_id: str, name: str):
    path = DATA_DIR / video_id / "clips" / name
    if not path.exists():
        return JSONResponse({"error": "file not found"}, status_code=404)
    return FileResponse(path)


app.include_router(api)