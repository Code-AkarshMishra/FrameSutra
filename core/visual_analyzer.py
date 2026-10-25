"""Optional sampled-frame visual analysis for local video files.

Frames are extracted locally with FFmpeg, near-duplicates are filtered locally,
and selected frames are sent to Groq's vision-capable API for descriptions.
This is opt-in because images leave the machine when vision analysis is enabled.
"""
from __future__ import annotations
import base64
import hashlib
import os
import subprocess
from pathlib import Path
import requests

from core.config import PROJECT_ROOT, load_project_env
from core.observability import increment

load_project_env()
FRAME_DIR = PROJECT_ROOT / "downloads" / "frames"


def _timestamp(seconds: int) -> str:
    h, rem = divmod(max(0, seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _average_hash(path: Path) -> int:
    # Lightweight duplicate detector; no extra image library required.
    try:
        from PIL import Image
        image = Image.open(path).convert("L").resize((8, 8))
        pixels = list(image.getdata())
        avg = sum(pixels) / len(pixels)
        value = 0
        for px in pixels:
            value = (value << 1) | int(px >= avg)
        return value
    except Exception:
        return int(hashlib.sha256(path.read_bytes()).hexdigest()[:16], 16)


def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def extract_sampled_frames(video_path: str, interval_seconds: int = 60, max_frames: int = 80, source_identity: str | None = None):
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError("Visual analysis currently requires a local video file path.")
    stat = path.stat()
    if not shutil_which("ffmpeg"):
        raise RuntimeError("FFmpeg is required for visual frame extraction.")
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    requested_interval = max(1, int(interval_seconds))
    duration = 0
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        duration = int(float(probe.stdout.strip())) if probe.returncode == 0 else 0
    except Exception:
        duration = 0
    # Sample across the whole recording rather than only the first N minutes.
    effective_interval = max(requested_interval, (duration + max_frames - 1) // max_frames if duration else requested_interval)
    identity = source_identity or f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    signature = f"{identity}|{effective_interval}|{max_frames}"
    run_dir = FRAME_DIR / hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]
    run_dir.mkdir(parents=True, exist_ok=True)
    cached_frames = sorted(run_dir.glob("frame_*.jpg"))
    if cached_frames:
        increment("visual_frame_cache_hits")
        selected, hashes = [], []
        for i, frame in enumerate(cached_frames):
            frame_hash = _average_hash(frame)
            if any(_hamming(frame_hash, old) <= 4 for old in hashes):
                continue
            hashes.append(frame_hash)
            selected.append((i * effective_interval, frame))
        return selected
    pattern = str(run_dir / "frame_%06d.jpg")
    fps = 1 / effective_interval
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-vf", f"fps={fps},scale=768:-2:force_original_aspect_ratio=decrease",
        "-q:v", "5", "-frames:v", str(max_frames), pattern, "-y",
    ]
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg frame extraction failed: {proc.stderr[-1000:]}")
    frames = sorted(run_dir.glob("frame_*.jpg"))
    selected, hashes = [], []
    for i, frame in enumerate(frames):
        h = _average_hash(frame)
        if any(_hamming(h, old) <= 4 for old in hashes):
            continue
        hashes.append(h)
        selected.append((i * effective_interval, frame))
    return selected


def shutil_which(command: str):
    import shutil
    return shutil.which(command)


def describe_frames_with_groq(frames, batch_size: int = 4) -> list[dict]:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key or "replace_with_" in api_key.lower():
        raise RuntimeError("Set a valid GROQ_API_KEY before enabling visual analysis.")
    model = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct").strip()
    output = []
    endpoint = "https://api.groq.com/openai/v1/chat/completions"
    for start in range(0, len(frames), max(1, batch_size)):
        batch = frames[start:start + max(1, batch_size)]
        content = [{
            "type": "text",
            "text": (
                "Describe each attached video frame separately for video search. "
                "Return one concise factual description per image, in the same order. "
                "Mention visible slide titles, code, diagrams, UI states and readable text. "
                "Do not guess unreadable content."
            ),
        }]
        for seconds, path in batch:
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            content.append({"type": "text", "text": f"Frame timestamp: {_timestamp(seconds)}"})
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}})
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": content}],
                  "temperature": 0.1, "max_tokens": 1400},
            timeout=180,
        )
        increment("groq_vision_calls")
        if response.status_code == 429:
            increment("groq_vision_rate_limits")
        if not response.ok:
            raise RuntimeError(
                f"Groq vision API returned {response.status_code}: {response.text[:600]}. "
                "Check GROQ_VISION_MODEL availability for your account."
            )
        text = response.json()["choices"][0]["message"]["content"]
        # Preserve source timestamps even if model output isn't perfectly formatted.
        lines = [line.strip(" -*\t") for line in text.splitlines() if line.strip()]
        for j, (seconds, path) in enumerate(batch):
            description = lines[j] if j < len(lines) else text.strip()
            output.append({"timestamp": _timestamp(seconds), "seconds": seconds,
                           "frame": str(path), "description": description})
    return output


def analyze_local_video(video_path: str, interval_seconds: int = 60, max_frames: int = 80, source_identity: str | None = None):
    path = Path(video_path).resolve()
    stat = path.stat()
    model = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct").strip()
    identity = source_identity or f"{path}|{stat.st_size}|{stat.st_mtime_ns}"
    cache_identity = f"{identity}|{interval_seconds}|{max_frames}|{model}"
    cache_key = hashlib.sha256(cache_identity.encode("utf-8")).hexdigest()[:24]
    cache_dir = PROJECT_ROOT / ".cache" / "visual"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{cache_key}.json"
    try:
        cached = __import__("json").loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else None
    except (OSError, ValueError):
        cached = None

    frames = extract_sampled_frames(str(path), interval_seconds, max_frames, source_identity=identity)
    if not frames:
        return []
    frame_by_timestamp = {_timestamp(seconds): frame for seconds, frame in frames}
    if cached:
        # Reuse completed vision descriptions if the media and settings are unchanged.
        cached_by_time = {item["timestamp"]: item for item in cached}
        if all(_timestamp(seconds) in cached_by_time for seconds, _ in frames):
            increment("visual_description_cache_hits")
            return [
                {**cached_by_time[_timestamp(seconds)], "frame": str(frame), "seconds": seconds}
                for seconds, frame in frames
            ]

    results = describe_frames_with_groq(frames)
    tmp = cache_file.with_suffix(".tmp")
    tmp.write_text(__import__("json").dumps(results, ensure_ascii=False), encoding="utf-8")
    tmp.replace(cache_file)
    return results
