import json
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
video = ffmpeg.overlay(video, logo, x='(main_w-overlay_w-40)', y='(main_h-overlay_h-40)')


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


outputs = []
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