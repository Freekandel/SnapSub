import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from dotenv import load_dotenv

from .utils import DATA_DIR, new_video_id, ensure_dir
from .clipper import generate_clips

load_dotenv()

app = FastAPI(title="SnapSub MVP API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    vid = new_video_id()
    vid_dir = ensure_dir(DATA_DIR / vid)
    in_path = vid_dir / f"input_{file.filename}"
    with open(in_path, "wb") as f:
        f.write(await file.read())
    return {"video_id": vid, "input_path": str(in_path)}


def format_srt_time(t: float) -> str:
    # SRT tijdformaat: HH:MM:SS,mmm
    ms = int((t - int(t)) * 1000)
    s = int(t) % 60
    m = (int(t) // 60) % 60
    h = int(t) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


@app.post("/api/generate")
async def api_generate(
    video_id: str = Form(...),
    n_clips: int = Form(3),
    clip_len: int = Form(20),
    scene_thresh: float = Form(0.3),
    use_whisper: int = Form(0),
):
    vid_dir = DATA_DIR / video_id
    if not vid_dir.exists():
        return JSONResponse({"error": "video_id not found"}, status_code=404)

    # vind input-bestand
    in_files = list(vid_dir.glob("input_*"))
    if not in_files:
        return JSONResponse({"error": "no input for video_id"}, status_code=400)
    input_path = in_files[0]

    srt_path: Optional[Path] = None
    if use_whisper:
        try:
            import whisper  # type: ignore
            model = whisper.load_model("small")
            result = model.transcribe(str(input_path))
            # Schrijf SRT
            srt_path = vid_dir / "subtitles.srt"
            with open(srt_path, "w", encoding="utf-8") as srt:
                idx = 1
                for seg in result["segments"]:
                    start = seg["start"]
                    end = seg["end"]
                    text = seg["text"].strip()
                    srt.write(f"{idx}\n")
                    srt.write(
                        f"{format_srt_time(start)} --> {format_srt_time(end)}\n"
                    )
                    srt.write(text + "\n\n")
                    idx += 1
        except Exception as e:
            print("Whisper error:", e)

    out_dir = ensure_dir(vid_dir / "clips")
    outputs = generate_clips(
        input_path=input_path,
        out_dir=out_dir,
        n_clips=n_clips,
        clip_len=clip_len,
        scene_thresh=scene_thresh,
        srt_path=srt_path,
    )

    files = [f"/api/download?video_id={video_id}&name={p.name}" for p in outputs]
    return {"video_id": video_id, "files": files}


@app.get("/api/download")
async def download(video_id: str, name: str):
    path = DATA_DIR / video_id / "clips" / name
    if not path.exists():
        return JSONResponse({"error": "file not found"}, status_code=404)
    return FileResponse(path)