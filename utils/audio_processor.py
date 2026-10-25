"""Audio/video ingestion for AI Video Assistant.

YouTube is downloaded into a unique job folder to prevent Windows .part-file
collisions when Streamlit has multiple sessions or a user retries a job.
The downloader uses yt-dlp's default player selection and asks for audio only;
it never falls back to downloading a whole video merely because audio formats
are temporarily unavailable.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import uuid
import warnings
import hashlib
from pathlib import Path

from core.config import PROJECT_ROOT
from core.observability import increment

warnings.filterwarnings(
    "ignore",
    message="FP16 is not supported on CPU",
    category=UserWarning,
)


def resolve_ffmpeg_dir() -> str | None:
    """Find FFmpeg and ffprobe, preferring a local Windows installation."""
    candidates = [
        os.path.join(os.path.expanduser("~"), "ffmpeg", "ffmpeg-9.0.2-full_build", "bin"),
        os.path.join(os.path.expanduser("~"), "ffmpeg", "bin"),
        r"C:\ffmpeg\bin",
        r"C:\Program Files\AI ExpertMeet\resources\bindings\FFmpeg",
        r"C:\Program Files\ffmpeg\bin",
        r"C:\Program Files\Git\usr\bin",
    ]
    for candidate in candidates:
        if os.path.isfile(os.path.join(candidate, "ffmpeg.exe")) and os.path.isfile(
            os.path.join(candidate, "ffprobe.exe")
        ):
            os.environ["PATH"] = candidate + os.pathsep + os.environ.get("PATH", "")
            return candidate

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        # yt-dlp also accepts the folder containing the binaries.
        return str(Path(ffmpeg).resolve().parent)
    return None


FFMPEG_DIR = resolve_ffmpeg_dir()
if FFMPEG_DIR:
    os.environ["PATH"] = FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")

import yt_dlp  # noqa: E402
from pydub import AudioSegment  # noqa: E402

if FFMPEG_DIR:
    _ffmpeg = str(Path(FFMPEG_DIR) / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"))
    _ffprobe = str(Path(FFMPEG_DIR) / ("ffprobe.exe" if os.name == "nt" else "ffprobe"))
    AudioSegment.converter = _ffmpeg
    AudioSegment.ffmpeg = _ffmpeg
    AudioSegment.ffprobe = _ffprobe

DOWNLOAD_DIR = PROJECT_ROOT / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
YOUTUBE_JOBS_DIR = DOWNLOAD_DIR / "youtube_jobs"
YOUTUBE_JOBS_DIR.mkdir(parents=True, exist_ok=True)
YOUTUBE_AUDIO_CACHE = DOWNLOAD_DIR / "youtube_audio_cache"
YOUTUBE_AUDIO_CACHE.mkdir(parents=True, exist_ok=True)


def _find_node() -> str | None:
    """Return Node.js path only when its major version supports current yt-dlp EJS."""
    candidates = [shutil.which("node"), r"C:\Program Files\nodejs\node.exe"]
    for candidate in candidates:
        if not candidate or not os.path.isfile(candidate):
            continue
        try:
            result = subprocess.run(
                [candidate, "--version"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            match = re.search(r"v?(\d+)", result.stdout.strip())
            if match and int(match.group(1)) >= 22:
                return str(Path(candidate).resolve())
        except (OSError, subprocess.SubprocessError):
            continue
    return None


NODE_PATH = _find_node()


def _make_ydl_opts(output_template: str) -> dict:
    """Build options using the current yt-dlp Python API contract."""
    opts: dict = {
        # Audio-only selector. Deliberately do not use `/best`, which may fetch
        # a full MP4 when YouTube's audio-only formats are not available.
        "format": "bestaudio",
        "outtmpl": output_template,
        "noplaylist": True,
        "windowsfilenames": True,
        "restrictfilenames": True,
        "overwrites": False,
        "continuedl": True,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 2,
        "file_access_retries": 3,
        "concurrent_fragment_downloads": 1,
        "quiet": True,
        "no_warnings": False,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
            }
        ],
        # Allow the current challenge-solver scripts to be fetched if the
        # matching yt-dlp-ejs package is not installed in this venv.
        "remote_components": ["ejs:github"],
    }
    if FFMPEG_DIR:
        opts["ffmpeg_location"] = FFMPEG_DIR
    if NODE_PATH:
        # Current yt-dlp API expects runtime -> config dict, not a string.
        opts["js_runtimes"] = {"node": {"path": NODE_PATH}}
    # If no supported Node is found, yt-dlp's default Deno runtime remains
    # enabled; Deno can be used when installed and discoverable on PATH.
    return opts


def _explain_download_error(exc: Exception) -> str:
    message = str(exc)
    lowered = message.lower()
    if (
        "requested format is not available" in lowered
        or "only images are available" in lowered
        or "signature solving failed" in lowered
        or "challenge solving failed" in lowered
        or "n challenge" in lowered
    ):
        return (
            "YouTube did not expose a downloadable audio format. Install the current "
            "yt-dlp challenge components in this virtual environment with: "
            'python -m pip install --upgrade "yt-dlp[default]". Then confirm that '
            "Node.js v22+ or Deno v2.3+ is installed, close other running copies of "
            "Streamlit, restart the app, and try the URL again."
        )
    if "winerror 32" in lowered or "unable to rename file" in lowered:
        return (
            "Windows locked a temporary download file. This version uses a separate "
            "folder for each attempt to avoid name collisions. Stop any other Streamlit "
            "terminals, restart this app, and retry once."
        )
    if "private video" in lowered or "sign in" in lowered or "members-only" in lowered:
        return (
            "This video may require sign-in or membership access. Try a publicly "
            "accessible video, or upload a local audio/video file instead."
        )
    # Don't put long Windows paths or yt-dlp control codes into the page.
    compact = " ".join(message.replace("\x1b", " ").split())
    return compact[:500] if compact else "Unknown YouTube download error. Check the terminal log."


def download_youtube_audio(url: str, retries: int = 2) -> str:
    """Download audio to WAV in a unique folder and return the WAV path."""
    if not url.lower().startswith(("https://", "http://")):
        raise ValueError("Expected an HTTP(S) URL for YouTube download.")

    canonical_url = url.strip().split("&list=", 1)[0]
    cache_file = YOUTUBE_AUDIO_CACHE / (hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:32] + ".wav")
    if cache_file.is_file() and cache_file.stat().st_size > 44:
        increment("youtube_audio_cache_hits")
        print("[yt-dlp] Reusing cached audio download.")
        return str(cache_file)

    last_exc: Exception | None = None
    attempts = max(1, min(int(retries), 3))

    for attempt in range(1, attempts + 1):
        # Never reuse the title-derived output path. This protects against
        # same-title videos, concurrent Streamlit sessions, and stale .part files.
        job_dir = YOUTUBE_JOBS_DIR / f"job_{uuid.uuid4().hex[:12]}"
        job_dir.mkdir(parents=True, exist_ok=False)
        output_template = str(job_dir / "%(id)s.%(ext)s")
        try:
            opts = _make_ydl_opts(output_template)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)

            wav_files = sorted(
                job_dir.glob("*.wav"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if wav_files and wav_files[0].is_file() and wav_files[0].stat().st_size > 44:
                tmp_cache = cache_file.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
                shutil.copy2(wav_files[0], tmp_cache)
                os.replace(tmp_cache, cache_file)
                return str(cache_file)

            # A successful-looking yt-dlp response without a WAV is not success.
            raise FileNotFoundError("yt-dlp returned without creating the processed WAV file.")

        except Exception as exc:
            last_exc = exc
            explanation = _explain_download_error(exc)
            lowered = str(exc).lower()
            is_retryable = any(
                token in lowered
                for token in ("timeout", "timed out", "connection", "network", "winerror 32", "unable to rename")
            )
            print(f"[yt-dlp] attempt {attempt}/{attempts} failed: {explanation}")
            if attempt < attempts and is_retryable:
                time.sleep(attempt * 2)
                continue
            raise RuntimeError(explanation) from exc

    raise RuntimeError(_explain_download_error(last_exc or RuntimeError("Unknown error")))


def convert_to_wav(input_path: str) -> str:
    """Convert local audio/video to 16-kHz mono WAV."""
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")
    output_path = os.path.splitext(input_path)[0] + "_converted.wav"
    audio = AudioSegment.from_file(input_path)
    audio = audio.set_channels(1).set_frame_rate(16000)
    audio.export(output_path, format="wav")
    return output_path


def chunk_audio(wav_path: str, chunk_minutes: int = 10) -> list[str]:
    """Split a WAV file into chunk_minutes-long segments."""
    if not os.path.exists(wav_path):
        raise FileNotFoundError(f"WAV file not found: {wav_path}")
    audio = AudioSegment.from_wav(wav_path)
    chunk_ms = chunk_minutes * 60 * 1000
    chunks: list[str] = []
    for index, start in enumerate(range(0, len(audio), chunk_ms)):
        chunk = audio[start : start + chunk_ms]
        chunk_path = f"{wav_path}_chunk_{index}.wav"
        chunk.export(chunk_path, format="wav")
        chunks.append(chunk_path)
    if not chunks:
        raise RuntimeError("The input audio appears to be empty; no audio chunks were created.")
    return chunks


def process_input(source: str) -> list[str]:
    """Accept a YouTube URL or local path and return WAV chunk paths."""
    source = source.strip()
    if not source:
        raise ValueError("Please provide a YouTube URL or a local media path.")
    if source.startswith(("http://", "https://")):
        print("Detected YouTube URL. Downloading audio...")
        wav_path = download_youtube_audio(source)
    else:
        print("Detected local file. Converting to WAV...")
        wav_path = convert_to_wav(source)
    print("Chunking audio...")
    chunks = chunk_audio(wav_path)
    print(f"Audio ready — {len(chunks)} chunk(s) created.")
    return chunks
