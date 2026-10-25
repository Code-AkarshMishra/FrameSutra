"""Local-first FastAPI service for the React FrameSutra interface."""
from __future__ import annotations

import hashlib
import asyncio
import json
import logging
import math
import os
import random
import re
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yt_dlp
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from core.analyzer import _extract_json, analyze_transcript, fallback_analysis, is_rate_limit_error
from core.config import PROJECT_ROOT, load_project_env
from core.job_store import (
    DB_PATH, add_chat_message, allow_event, cleanup_expired_jobs, count_jobs, count_owner_jobs_since, count_other_jobs_for_source,
    create_job as db_create_job, delete_bookmark, delete_job as db_delete_job,
    delete_study_set, get_answer_cache, get_bookmarks, get_chat_messages, get_job as db_get_job, get_study_set, has_other_job_with_transcript,
    jobs_with_collection, list_jobs, put_bookmark, save_study_set, set_checkpoint,
    save_answer_cache, set_saved, update_job as db_update_job,
)
from core.llm_provider import configured_model, get_llm, invoke_with_retry
from core.observability import increment, snapshot
from core.rag_engine import answer_from_sources, ask_question, build_rag_chain, retrieve_sources, load_rag_chain
from core.transcriber import SARVAM_MODEL, WHISPER_MODEL, transcribe_all
from core.vector_store import build_vector_store, delete_vector_store, collection_for_text
from core.visual_analyzer import analyze_local_video
from utils.audio_processor import process_input

load_project_env()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("framesutra.api")

app = FastAPI(title="FrameSutra API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"]
)

WORKERS = max(1, int(os.getenv("VIDEO_JOB_WORKERS", "1")))
MAX_OUTSTANDING = max(WORKERS, int(os.getenv("MAX_OUTSTANDING_JOBS", "3")))
MAX_UPLOAD_BYTES = max(10, int(os.getenv("MAX_UPLOAD_MB", "512"))) * 1024 * 1024
MAX_MEDIA_SECONDS = max(60, int(os.getenv("MAX_MEDIA_HOURS", "6")) * 3600)
JOB_RETENTION_DAYS = max(1, int(os.getenv("JOB_RETENTION_DAYS", "30")))
MEDIA_RETENTION_DAYS = max(1, int(os.getenv("MEDIA_RETENTION_DAYS", "7")))
JOB_HOURLY_LIMIT = max(1, int(os.getenv("JOB_HOURLY_LIMIT", "5")))
CHAT_PER_MINUTE_LIMIT = max(1, int(os.getenv("CHAT_PER_MINUTE_LIMIT", "15")))
_executor = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="framesutra-job")
_lock = threading.RLock()
_futures: dict[str, Future] = {}
_rag_chains: dict[str, Any] = {}
_uploads = PROJECT_ROOT / "uploads"
_uploads.mkdir(parents=True, exist_ok=True)
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
_MEDIA_EXTENSIONS = _VIDEO_EXTENSIONS | {".mp3", ".wav", ".m4a", ".mpeg", ".mpga", ".ogg", ".flac"}
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}


@app.middleware("http")
async def reject_oversized_upload(request: Request, call_next):
    if request.url.path in {"/api/jobs", "/api/jobs/batch"}:
        length = request.headers.get("content-length")
        max_request = MAX_UPLOAD_BYTES * (3 if request.url.path.endswith("/batch") else 1) + 1024 * 1024
        if length and length.isdigit() and int(length) > max_request:
            return JSONResponse({"detail": "Request body exceeds the configured upload limit."}, status_code=413)
    return await call_next(request)


class JobCancelled(Exception):
    pass


def _owner(request: Request) -> str:
    # Do not trust X-Forwarded-For unless a trusted proxy is explicitly set up.
    return request.client.host if request.client else "local"


def _limit_or_429(key: str, limit: int, seconds: int, detail: str) -> None:
    allowed, retry = allow_event(key, limit, seconds)
    if not allowed:
        raise HTTPException(429, detail, headers={"Retry-After": str(retry)})


def _api_key_present(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return bool(value) and not any(marker in value for marker in ("replace_with_", "your_actual_", "your_real_", "api_key_here"))


def _validate_youtube_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in _YOUTUBE_HOSTS:
        raise HTTPException(400, "Use a public HTTPS YouTube or youtu.be URL.")
    return url.strip()


def _media_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise HTTPException(503, "FFprobe is required to check media duration. Install FFmpeg and restart the API.")
    proc = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)], capture_output=True, text=True, timeout=45)
    try:
        duration = float(proc.stdout.strip())
    except (ValueError, TypeError):
        raise HTTPException(415, "Could not read media duration. Check the file and FFmpeg installation.")
    if proc.returncode != 0 or duration <= 0:
        raise HTTPException(415, "The media file appears invalid or has no audio duration.")
    if duration > MAX_MEDIA_SECONDS:
        raise HTTPException(413, f"Media is longer than the {MAX_MEDIA_SECONDS // 3600}-hour limit.")
    return duration


async def _save_upload(media: UploadFile) -> tuple[str, str, float]:
    extension = Path(media.filename or "").suffix.lower()
    if extension not in _MEDIA_EXTENSIONS:
        raise HTTPException(415, "Choose a supported audio or video file.")
    target = _uploads / f"{uuid.uuid4().hex}{extension}"
    digest = hashlib.sha256()
    size = 0
    try:
        with target.open("wb") as out:
            while block := await media.read(1024 * 1024):
                size += len(block)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"Upload exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")
                digest.update(block)
                out.write(block)
        _media_duration(target)
        return str(target), digest.hexdigest(), size
    except Exception:
        target.unlink(missing_ok=True)
        raise


def _enqueue(owner: str, source: str, language: str, options: dict[str, Any], job_id: str | None = None, checkpoints: dict[str, Any] | None = None) -> str:
    with _lock:
        outstanding = count_jobs(("queued", "running"))
        if outstanding >= MAX_OUTSTANDING:
            increment("jobs_rejected_queue_full")
            raise HTTPException(429, "The analysis queue is full. Wait for a job to finish, then try again.", headers={"Retry-After": "30"})
        identity = job_id or uuid.uuid4().hex
        if job_id:
            db_update_job(identity, state="queued", error=None, finished_at=None, cancel_requested=False)
        else:
            db_create_job(identity, owner, source, language, options, checkpoints)
        future = _executor.submit(_run_job, identity)
        _futures[identity] = future
        future.add_done_callback(lambda _: _futures.pop(identity, None))
        increment("jobs_submitted")
        logger.info("job_queued job_id=%s owner=%s source_kind=%s", identity, owner, "youtube" if source.startswith("https://") else "upload")
        return identity


def _cancel_check(job_id: str) -> None:
    job = db_get_job(job_id)
    if job is None or job["cancel_requested"]:
        raise JobCancelled()


def _chapters_from_transcript(transcript: str) -> list[dict[str, Any]]:
    markers = list(re.finditer(r"\[(?:Speech timestamp |Approx\. timestamp )(\d{2}:\d{2}:\d{2})\]\s*", transcript))
    chapters = []
    used_windows: set[int] = set()
    for index, marker in enumerate(markers):
        hours, minutes, seconds = (int(part) for part in marker.group(1).split(":"))
        window = (hours * 3600 + minutes * 60 + seconds) // 600
        if window in used_windows:
            continue
        used_windows.add(window)
        end = markers[index + 1].start() if index + 1 < len(markers) else len(transcript)
        # Use a few following speech segments for a readable local chapter title.
        following = next((m for m in markers[index + 1:] if (int(m.group(1)[:2]) * 3600 + int(m.group(1)[3:5]) * 60 + int(m.group(1)[6:])) // 600 > window), None)
        if following:
            end = following.start()
        text = re.sub(r"\s+", " ", transcript[marker.end():end]).strip()
        sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
        title = " ".join(sentence.split()[:8]).strip(" .,:;-") or f"Chapter {index + 1}"
        chapters.append({"timestamp": marker.group(1), "title": title[:72], "index": len(chapters)})
    return chapters


def _run_job(job_id: str) -> None:
    job = db_get_job(job_id)
    if not job:
        return
    source, language, options = job["source"], job["language"], job["options"]
    checkpoints = job["checkpoints"] or {}
    cached_audio = bool(checkpoints.get("audio_chunks"))
    cached_transcript = bool(checkpoints.get("transcript"))
    cached_analysis = bool(checkpoints.get("analysis"))
    cached_visuals = "visual_evidence" in checkpoints
    started = time.monotonic()
    steps = job["steps"] or {}
    stage_times = job["stage_times"] or {}
    active_started: dict[str, float] = {}
    db_update_job(job_id, state="running", started_at=job.get("started_at") or datetime.now(timezone.utc).isoformat(), error=None)

    def progress(step: str, state: str, detail: str = "") -> None:
        now = time.monotonic()
        previous = (steps.get(step) or {}).get("state")
        if state == "active" and previous != "active":
            active_started[step] = now
            logger.info("job_stage_started job_id=%s stage=%s", job_id, step)
        if state in {"done", "error", "skipped"} and step in active_started:
            elapsed = round(now - active_started.pop(step), 3)
            stage_times[step] = stage_times.get(step, 0) + elapsed
            logger.info("job_stage_finished job_id=%s stage=%s state=%s duration_seconds=%.3f", job_id, step, state, elapsed)
        steps[step] = {"state": state, "detail": detail}
        db_update_job(job_id, steps=steps, stage_times=stage_times)

    try:
        _cancel_check(job_id)
        chunks = checkpoints.get("audio_chunks")
        if not chunks or not all(Path(path).is_file() for path in chunks):
            if checkpoints.get("transcript"):
                chunks = []
                progress("audio", "skipped", "Source media expired; continuing from saved transcript")
            else:
                progress("audio", "active", "Checking media duration and preparing audio")
                if source.startswith("https://"):
                    with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "noplaylist": True}) as ydl:
                        info = ydl.extract_info(source, download=False)
                    duration = float(info.get("duration") or 0)
                    if duration and duration > MAX_MEDIA_SECONDS:
                        raise RuntimeError(f"Video exceeds the {MAX_MEDIA_SECONDS // 3600}-hour duration limit.")
                else:
                    try:
                        _media_duration(Path(source))
                    except HTTPException as exc:
                        raise RuntimeError(exc.detail) from exc
                _cancel_check(job_id)
                chunks = [str(item) for item in process_input(source)]
                checkpoints["audio_chunks"] = chunks
                set_checkpoint(job_id, "audio_chunks", chunks)
                progress("audio", "done", f"Prepared {len(chunks)} audio segment(s)")
        else:
            increment("cache_audio_hits")
            progress("audio", "done", "Reused prepared audio checkpoint")

        _cancel_check(job_id)
        transcript = checkpoints.get("transcript")
        if not transcript:
            progress("transcript", "active", "Transcribing speech")
            source_id = options.get("source_hash") or source
            def report_transcription_progress(done: int, total: int) -> None:
                _cancel_check(job_id)
                progress("transcript", "active", f"Transcribed audio chunk {done}/{total}")
            transcript = transcribe_all(chunks, language, source_id=source_id, progress_callback=report_transcription_progress)
            checkpoints["transcript"] = transcript
            set_checkpoint(job_id, "transcript", transcript)
            progress("transcript", "done", "Transcript checkpoint saved")
        else:
            increment("cache_transcript_hits")
            progress("transcript", "done", "Reused transcript checkpoint")

        _cancel_check(job_id)
        analysis = checkpoints.get("analysis")
        if not analysis:
            for step in ("title", "summary", "extract"):
                progress(step, "active", "Generating structured notes")
            try:
                analysis = analyze_transcript(transcript)
            except Exception as exc:
                if not is_rate_limit_error(exc):
                    raise
                analysis = fallback_analysis(transcript)
                logger.warning("job_analysis_fallback job_id=%s reason=provider_rate_limit", job_id)
            checkpoints["analysis"] = analysis
            set_checkpoint(job_id, "analysis", analysis)
            for step in ("title", "summary", "extract"):
                progress(step, "done", "Analysis checkpoint saved")
        else:
            increment("cache_analysis_hits")
            for step in ("title", "summary", "extract"):
                progress(step, "done", "Reused analysis checkpoint")

        _cancel_check(job_id)
        evidence = checkpoints.get("visual_evidence")
        if evidence is None:
            if options.get("include_visuals") and not source.startswith("https://") and Path(source).is_file() and Path(source).suffix.lower() in _VIDEO_EXTENSIONS:
                progress("visual", "active", "Sampling and describing video frames")
                evidence = analyze_local_video(source, interval_seconds=int(options.get("interval", 60)), max_frames=int(options.get("max_frames", 40)), source_identity=options.get("source_hash"))
                set_checkpoint(job_id, "visual_evidence", evidence)
                progress("visual", "done", f"Indexed {len(evidence)} visual frame(s)")
            else:
                evidence = []
                set_checkpoint(job_id, "visual_evidence", evidence)
                progress("visual", "skipped", "Visual analysis is available for uploaded local video")
        else:
            if cached_visuals:
                increment("cache_visual_hits")
            progress("visual", "done" if evidence else "skipped", "Reused visual checkpoint" if evidence else "No visual notes for this source")

        _cancel_check(job_id)
        corpus = transcript
        if evidence:
            corpus += "\n\nVISUAL EVIDENCE\n" + "\n\n".join(f"[VISUAL FRAME {item['timestamp']}] {item['description']}" for item in evidence)
        progress("rag", "active", "Building or reusing the transcript search index")
        chain = build_rag_chain(corpus)
        collection_name = collection_for_text(corpus)
        _rag_chains[job_id] = chain
        progress("rag", "done", "Search index ready")
        result = {
            "source": source if source.startswith("https://") else Path(source).name,
            "audio_chunks": chunks, "title": analysis["title"], "transcript": transcript,
            "timestamp_quality": "Whisper speech segments" if language == "english" and "[Speech timestamp " in transcript else "Approximate 10-minute segment start",
            "summary": analysis["summary"], "action_items": analysis["action_items"],
            "key_decisions": analysis["key_decisions"], "open_questions": analysis["open_questions"],
            "chunk_count": len(chunks), "language": language,
            "used_fallback": analysis.get("used_fallback", False),
            "visual_evidence": [{"timestamp": x.get("timestamp"), "description": x.get("description")} for x in evidence],
            "chapters": _chapters_from_transcript(transcript),
        }
        db_update_job(job_id, state="complete", result=result, collection_name=collection_name,
                      finished_at=datetime.now(timezone.utc).isoformat(), cancel_requested=False)
        increment("jobs_completed")
        logger.info("job_complete job_id=%s total_seconds=%.3f cache_audio=%s cache_transcript=%s cache_analysis=%s cache_visuals=%s", job_id, time.monotonic() - started, cached_audio, cached_transcript, cached_analysis, cached_visuals)
    except JobCancelled:
        db_update_job(job_id, state="cancelled", error="Job cancelled by user.", finished_at=datetime.now(timezone.utc).isoformat(), cancel_requested=False)
        increment("jobs_cancelled")
        logger.info("job_cancelled job_id=%s", job_id)
    except Exception as exc:
        latest = db_get_job(job_id)
        if latest and latest["cancel_requested"]:
            db_update_job(job_id, state="cancelled", error="Job cancelled by user.", finished_at=datetime.now(timezone.utc).isoformat(), cancel_requested=False)
            increment("jobs_cancelled")
            return
        current = next((name for name, value in steps.items() if value.get("state") == "active"), "pipeline")
        progress(current, "error", str(exc)[:800])
        db_update_job(job_id, state="error", error=str(exc)[:1000], finished_at=datetime.now(timezone.utc).isoformat())
        increment("jobs_failed")
        logger.exception("job_failed job_id=%s stage=%s", job_id, current)
    finally:
        _futures.pop(job_id, None)


def _owned_job(job_id: str, owner: str) -> dict[str, Any]:
    job = db_get_job(job_id)
    if not job or job["owner"] != owner:
        raise HTTPException(404, "Analysis job not found.")
    return job


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result")
    if result:
        result = {**result, "audio_chunks": list(range(len(result.get("audio_chunks", []))))}
    return {"id": job["id"], "state": job["state"], "steps": job["steps"], "stage_times": job["stage_times"],
            "result": result, "error": job["error"], "created_at": job["created_at"], "updated_at": job["updated_at"],
            "saved": job["saved"], "cancel_requested": job["cancel_requested"], "retry_available": job["state"] in {"error", "interrupted", "cancelled"}}


def _load_chain(job: dict[str, Any]):
    with _lock:
        chain = _rag_chains.get(job["id"])
        if chain:
            return chain
        if not job.get("collection_name"):
            return None
        chain = load_rag_chain(job["collection_name"])
        _rag_chains[job["id"]] = chain
        return chain


def _job_corpus(job: dict[str, Any]) -> str:
    result = job.get("result") or {}
    corpus = str(result.get("transcript") or "")
    evidence = result.get("visual_evidence") or []
    if evidence:
        corpus += "\n\nVISUAL EVIDENCE\n" + "\n\n".join(
            f"[VISUAL FRAME {item.get('timestamp', 'unknown')}] {item.get('description', '')}"
            for item in evidence
        )
    return corpus


def _ensure_timestamp_index(job: dict[str, Any]) -> dict[str, Any]:
    """Rebuild older Chroma collections once using clean timestamp metadata."""
    corpus = _job_corpus(job)
    if not corpus.strip():
        raise HTTPException(409, "This analysis has no transcript index to search.")
    expected = collection_for_text(corpus)
    if job.get("collection_name") == expected:
        return job
    old_collection = job.get("collection_name")
    build_vector_store(corpus)
    db_update_job(job["id"], collection_name=expected)
    job["collection_name"] = expected
    _rag_chains.pop(job["id"], None)
    if old_collection and old_collection != expected and jobs_with_collection(old_collection) == 0:
        try:
            delete_vector_store(old_collection)
        except Exception:
            logger.exception("old_vector_collection_cleanup_failed job_id=%s", job["id"])
    logger.info("chat_index_migrated job_id=%s collection=%s", job["id"], expected)
    return job


def _remove_job_files(job: dict[str, Any]) -> None:
    roots = [(PROJECT_ROOT / "downloads").resolve(), _uploads.resolve()]
    paths = list((job.get("result") or {}).get("audio_chunks", [])) + list((job.get("checkpoints") or {}).get("audio_chunks", []))
    options = job.get("options") or {}
    identity = options.get("source_hash") or job["source"]
    if count_other_jobs_for_source(job["owner"], identity, job["language"], job["id"]) == 0:
        model_id = SARVAM_MODEL if job["language"] == "hinglish" else WHISPER_MODEL
        transcript_key = hashlib.sha256(f"timestamped-v2|{identity}|{job['language']}|{model_id}".encode("utf-8")).hexdigest()[:24]
        (PROJECT_ROOT / ".cache" / "transcripts" / f"{transcript_key}.json").unlink(missing_ok=True)
    if count_other_jobs_for_source(job["owner"], identity, None, job["id"]) == 0:
        for item in paths:
            chunk_path = Path(item)
            if chunk_path.is_file():
                stat = chunk_path.stat()
                signature = f"{chunk_path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
                piece_key = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:24]
                (PROJECT_ROOT / ".cache" / "sarvam_pieces" / f"{piece_key}.json").unlink(missing_ok=True)
        transcript = (job.get("result") or {}).get("transcript") or (job.get("checkpoints") or {}).get("transcript")
        if transcript and not has_other_job_with_transcript(transcript, job["id"]):
            analysis_key = hashlib.sha256(f"analysis-cache-v2|{configured_model()}|{transcript}".encode("utf-8")).hexdigest()[:24]
            (PROJECT_ROOT / ".cache" / "analysis_results" / f"{analysis_key}.json").unlink(missing_ok=True)
            (PROJECT_ROOT / ".cache" / "analysis" / f"{analysis_key}.json").unlink(missing_ok=True)
        if options.get("include_visuals") and options.get("source_hash"):
            vision_model = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct").strip()
            visual_identity = f"{identity}|{options.get('interval', 60)}|{options.get('max_frames', 40)}|{vision_model}"
            visual_key = hashlib.sha256(visual_identity.encode("utf-8")).hexdigest()[:24]
            (PROJECT_ROOT / ".cache" / "visual" / f"{visual_key}.json").unlink(missing_ok=True)
            source_path = Path(job["source"])
            ffprobe = shutil.which("ffprobe")
            if source_path.is_file() and ffprobe:
                try:
                    probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(source_path)], capture_output=True, text=True, timeout=20)
                    duration = float(probe.stdout.strip()) if probe.returncode == 0 else 0
                    interval = max(int(options.get("interval", 60)), math.ceil(duration / max(1, int(options.get("max_frames", 40)))))
                    frame_identity = f"{identity}|{interval}|{options.get('max_frames', 40)}"
                    frame_key = hashlib.sha256(frame_identity.encode("utf-8")).hexdigest()[:16]
                    shutil.rmtree(PROJECT_ROOT / "downloads" / "frames" / frame_key, ignore_errors=True)
                except (OSError, ValueError, subprocess.SubprocessError):
                    logger.warning("job_frame_cleanup_failed job_id=%s", job["id"])
        if str(job["source"]).startswith("https://"):
            canonical = str(job["source"]).strip().split("&list=", 1)[0]
            cache_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
            (PROJECT_ROOT / "downloads" / "youtube_audio_cache" / f"{cache_key}.wav").unlink(missing_ok=True)
    if not str(job["source"]).startswith("https://"):
        paths.append(job["source"])
        source_path = Path(job["source"])
        paths.append(str(source_path.with_suffix("")) + "_converted.wav")
    for item in paths:
        path = Path(item).resolve()
        if any(path == root or root in path.parents for root in roots):
            path.unlink(missing_ok=True)


def _remove_old_files(root: Path, days: int) -> int:
    if not root.exists():
        return 0
    cutoff = datetime.now().timestamp() - days * 86400
    removed = 0
    for path in root.rglob("*"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        except OSError:
            logger.warning("cleanup_skip path=%s", path)
    for path in sorted(root.rglob("*"), reverse=True):
        try:
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        except OSError:
            pass
    return removed


def run_cleanup() -> dict[str, int]:
    if count_jobs(("queued", "running")):
        logger.info("cleanup_deferred reason=active_jobs")
        return {"expired_jobs": 0, "removed_media_files": 0, "removed_cache_files": 0, "skipped_active_jobs": 1}
    expired = cleanup_expired_jobs(JOB_RETENTION_DAYS)
    for item in expired:
        if item.get("collection_name") and jobs_with_collection(item["collection_name"]) == 0:
            try:
                delete_vector_store(item["collection_name"])
            except Exception:
                logger.exception("cleanup_chroma_failed collection=%s", item["collection_name"])
        _remove_job_files(item)
        _rag_chains.pop(item["id"], None)
    media_roots = [PROJECT_ROOT / "downloads" / "youtube_audio_cache", PROJECT_ROOT / "downloads" / "youtube_jobs", PROJECT_ROOT / "downloads" / "frames", _uploads]
    removed_media = sum(_remove_old_files(root, MEDIA_RETENTION_DAYS) for root in media_roots)
    cache_roots = [PROJECT_ROOT / ".cache" / name for name in ("transcripts", "analysis", "analysis_results", "sarvam_pieces", "visual")]
    removed_cache = sum(_remove_old_files(root, JOB_RETENTION_DAYS) for root in cache_roots)
    increment("cleanup_jobs_removed", len(expired))
    logger.info("cleanup_complete expired_jobs=%d media_files=%d cache_files=%d", len(expired), removed_media, removed_cache)
    return {"expired_jobs": len(expired), "removed_media_files": removed_media, "removed_cache_files": removed_cache}


@app.on_event("startup")
async def startup_cleanup() -> None:
    run_cleanup()
    async def cleanup_loop() -> None:
        while True:
            await asyncio.sleep(24 * 60 * 60)
            await asyncio.to_thread(run_cleanup)
    app.state.cleanup_task = asyncio.create_task(cleanup_loop())


@app.on_event("shutdown")
async def stop_cleanup() -> None:
    task = getattr(app.state, "cleanup_task", None)
    if task:
        task.cancel()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": "FrameSutra"}


@app.get("/api/metrics")
def metrics() -> dict[str, Any]:
    usage = shutil.disk_usage(PROJECT_ROOT)
    return {"jobs": {"queued_or_running": count_jobs(("queued", "running")), "completed": count_jobs(("complete",)),
                      "failed": count_jobs(("error", "interrupted")), "cancelled": count_jobs(("cancelled",))},
            "queue_capacity": MAX_OUTSTANDING, "workers": WORKERS,
            "limits": {"upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024), "media_hours": MAX_MEDIA_SECONDS // 3600,
                       "jobs_per_hour": JOB_HOURLY_LIMIT, "chat_per_minute": CHAT_PER_MINUTE_LIMIT},
            "retention_days": JOB_RETENTION_DAYS, "media_retention_days": MEDIA_RETENTION_DAYS,
            "disk": {"total_bytes": usage.total, "free_bytes": usage.free, "used_bytes": usage.used},
            "provider_counters": snapshot()}


@app.get("/api/library")
def library(request: Request, q: str = "", limit: int = 100) -> list[dict[str, Any]]:
    owner = _owner(request)
    items = []
    for job in list_jobs(owner, q, limit):
        result = job.get("result") or {}
        items.append({"id": job["id"], "state": job["state"], "steps": job["steps"], "error": job["error"],
                      "created_at": job["created_at"], "updated_at": job["updated_at"], "saved": job["saved"],
                      "retry_available": job["state"] in {"error", "interrupted", "cancelled"},
                      "result": {"title": result.get("title"), "source": result.get("source", job["source"] if job["source"].startswith("https://") else Path(job["source"]).name),
                                 "language": result.get("language", job["language"]), "chunk_count": result.get("chunk_count", 0)}})
    return items


@app.post("/api/jobs")
async def create_job(request: Request, language: str = Form("english"), source_url: str = Form(""),
                     include_visuals: bool = Form(False), interval: int = Form(60), max_frames: int = Form(40),
                     media: UploadFile | None = File(None)) -> dict[str, str]:
    language = language.strip().lower()
    if language not in {"english", "hinglish"}:
        raise HTTPException(400, "Language must be English or Hinglish.")
    if not _api_key_present("GROQ_API_KEY"):
        raise HTTPException(503, "GROQ_API_KEY is not configured on the server.")
    if language == "hinglish" and not _api_key_present("SARVAM_API_KEY"):
        raise HTTPException(503, "SARVAM_API_KEY is required for Hinglish transcription.")
    owner = _owner(request)
    _limit_or_429(f"job-cooldown:{owner}", 1, 20, "Wait 20 seconds before submitting another analysis.")
    if count_owner_jobs_since(owner, 3600) >= JOB_HOURLY_LIMIT:
        raise HTTPException(429, "Hourly analysis limit reached. Try again later.", headers={"Retry-After": "3600"})
    if media is not None and media.filename:
        source, source_hash, size = await _save_upload(media)
        options = {"include_visuals": include_visuals, "interval": max(15, interval), "max_frames": max(10, min(max_frames, 120)), "source_hash": source_hash, "upload_bytes": size}
    else:
        source = _validate_youtube_url(source_url)
        options = {"include_visuals": False, "interval": 60, "max_frames": 40}
    try:
        job_id = _enqueue(owner, source, language, options)
    except Exception:
        if not source.startswith("https://"):
            Path(source).unlink(missing_ok=True)
        raise
    return {"job_id": job_id}


@app.post("/api/jobs/batch")
async def create_batch(request: Request, sources: str = Form("[]"), language: str = Form("english"),
                       include_visuals: bool = Form(False), media: list[UploadFile] = File(default=[])) -> dict[str, Any]:
    try:
        urls = json.loads(sources)
    except json.JSONDecodeError:
        raise HTTPException(400, "Batch sources must be a JSON list of YouTube links.")
    if not isinstance(urls, list) or len(urls) + len([x for x in media if x.filename]) < 1:
        raise HTTPException(400, "Add at least one YouTube URL or file.")
    uploads = [x for x in media if x.filename]
    total = len(urls) + len(uploads)
    if total > 3:
        raise HTTPException(413, "A batch can contain up to three sources.")
    language = language.strip().lower()
    if language not in {"english", "hinglish"}:
        raise HTTPException(400, "Language must be English or Hinglish.")
    if not _api_key_present("GROQ_API_KEY") or (language == "hinglish" and not _api_key_present("SARVAM_API_KEY")):
        raise HTTPException(503, "Configure the required Groq and Sarvam API keys before submitting this batch.")
    owner = _owner(request)
    _limit_or_429(f"job-cooldown:{owner}", 1, 20, "Wait 20 seconds before submitting another batch.")
    already_used = count_owner_jobs_since(owner, 3600)
    if already_used + total > JOB_HOURLY_LIMIT:
        raise HTTPException(429, f"This batch would exceed your remaining hourly allowance of {max(0, JOB_HOURLY_LIMIT-already_used)} job(s).", headers={"Retry-After": "3600"})
    prepared: list[tuple[str, dict[str, Any]]] = []
    for url in urls:
        prepared.append((_validate_youtube_url(str(url)), {"include_visuals": False, "interval": 60, "max_frames": 40}))
    try:
        for upload in uploads:
            source, source_hash, size = await _save_upload(upload)
            prepared.append((source, {"include_visuals": include_visuals, "interval": 60, "max_frames": 40, "source_hash": source_hash, "upload_bytes": size}))
        ids = []
        with _lock:
            if count_jobs(("queued", "running")) + len(prepared) > MAX_OUTSTANDING:
                raise HTTPException(429, f"There is room for {max(0, MAX_OUTSTANDING - count_jobs(('queued','running')))} more job(s) in the queue.", headers={"Retry-After": "30"})
            for source, options in prepared:
                ids.append(_enqueue(owner, source, language, options))
        increment("batches_submitted")
        return {"job_ids": ids}
    except Exception:
        for source, _ in prepared:
            path = Path(source)
            if path.is_relative_to(_uploads) and path.exists():
                path.unlink(missing_ok=True)
        raise


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict[str, Any]:
    return _public_job(_owned_job(job_id, _owner(request)))


@app.get("/api/jobs/{job_id}/audio/{chunk_index}")
def get_audio_chunk(job_id: str, chunk_index: int, request: Request) -> FileResponse:
    job = _owned_job(job_id, _owner(request))
    paths = (job.get("result") or {}).get("audio_chunks", [])
    if chunk_index < 0 or chunk_index >= len(paths):
        raise HTTPException(404, "Audio segment not found.")
    path = Path(paths[chunk_index]).resolve()
    roots = [(PROJECT_ROOT / "downloads").resolve(), _uploads.resolve()]
    if not any(path == root or root in path.parents for root in roots):
        raise HTTPException(403, "Audio segment is outside the media workspace.")
    if not path.is_file():
        raise HTTPException(404, "Audio segment was removed by the retention policy.")
    return FileResponse(path, media_type="audio/wav", filename=path.name)


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, request: Request) -> dict[str, str]:
    job = _owned_job(job_id, _owner(request))
    if job["state"] not in {"error", "interrupted", "cancelled"}:
        raise HTTPException(409, "Only failed, interrupted, or cancelled jobs can be retried.")
    if not job["source"].startswith("https://") and not Path(job["source"]).is_file() and not job["checkpoints"].get("transcript"):
        raise HTTPException(410, "The uploaded source expired. Upload it again to retry.")
    if count_owner_jobs_since(job["owner"], 3600) >= JOB_HOURLY_LIMIT:
        raise HTTPException(429, "Hourly analysis limit reached. Try again later.", headers={"Retry-After": "3600"})
    new_id = _enqueue(job["owner"], job["source"], job["language"], job["options"], checkpoints=job["checkpoints"])
    return {"job_id": new_id}


@app.post("/api/jobs/{job_id}/retimestamp")
def retimestamp_job(job_id: str, request: Request) -> dict[str, str]:
    """Create a fresh analysis from retained audio to add Whisper segment times."""
    job = _owned_job(job_id, _owner(request))
    if job["state"] != "complete":
        raise HTTPException(409, "Only completed analyses can be refreshed.")
    if job["language"] != "english":
        raise HTTPException(409, "Speech-aligned timestamps are currently available for Whisper English transcription.")
    if not _api_key_present("GROQ_API_KEY"):
        raise HTTPException(503, "GROQ_API_KEY is required to create the refreshed analysis.")
    chunks = (job.get("result") or {}).get("audio_chunks", [])
    if not chunks or not all(Path(path).is_file() for path in chunks):
        raise HTTPException(410, "The processed audio has expired. Submit the original video again for precise timestamps.")
    owner = job["owner"]
    _limit_or_429(f"job-cooldown:{owner}", 1, 20, "Wait 20 seconds before submitting another analysis.")
    if count_owner_jobs_since(owner, 3600) >= JOB_HOURLY_LIMIT:
        raise HTTPException(429, "Hourly analysis limit reached. Try again later.", headers={"Retry-After": "3600"})
    result = job.get("result") or {}
    checkpoints = {
        "audio_chunks": chunks,
        "visual_evidence": result.get("visual_evidence", []),
        "analysis": {key: result.get(key, "") for key in ("title", "summary", "action_items", "key_decisions", "open_questions")},
    }
    checkpoints["analysis"]["used_fallback"] = result.get("used_fallback", False)
    new_id = _enqueue(owner, job["source"], job["language"], job["options"], checkpoints=checkpoints)
    increment("timestamp_refreshes")
    return {"job_id": new_id}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request) -> dict[str, str]:
    job = _owned_job(job_id, _owner(request))
    if job["state"] not in {"queued", "running"}:
        raise HTTPException(409, "This job is not running or queued.")
    future = _futures.get(job_id)
    if future and future.cancel():
        db_update_job(job_id, state="cancelled", error="Job cancelled before it started.", finished_at=datetime.now(timezone.utc).isoformat())
        _futures.pop(job_id, None)
        increment("jobs_cancelled")
    else:
        db_update_job(job_id, cancel_requested=True)
    return {"status": "cancellation requested"}


@app.delete("/api/jobs/{job_id}")
def remove_job(job_id: str, request: Request) -> dict[str, str]:
    job = _owned_job(job_id, _owner(request))
    if job["state"] in {"running", "queued"}:
        raise HTTPException(409, "Cancel the job before deleting it.")
    deleted = db_delete_job(job_id, _owner(request))
    _rag_chains.pop(job_id, None)
    _remove_job_files(deleted)
    if deleted.get("collection_name") and jobs_with_collection(deleted["collection_name"]) == 0:
        delete_vector_store(deleted["collection_name"])
    increment("jobs_deleted")
    return {"status": "deleted"}


@app.patch("/api/jobs/{job_id}/saved")
def save_analysis(job_id: str, request: Request, body: dict[str, bool]) -> dict[str, bool]:
    owner = _owner(request)
    _owned_job(job_id, owner)
    saved = bool(body.get("saved"))
    set_saved(job_id, owner, saved)
    return {"saved": saved}


@app.get("/api/jobs/{job_id}/bookmarks")
def bookmarks(job_id: str, request: Request) -> list[dict[str, Any]]:
    _owned_job(job_id, _owner(request))
    return get_bookmarks(job_id)


@app.post("/api/jobs/{job_id}/bookmarks")
def create_bookmark(job_id: str, request: Request, body: dict[str, str]) -> dict[str, Any]:
    _owned_job(job_id, _owner(request))
    timestamp = body.get("timestamp", "").strip()
    note = body.get("note", "").strip()
    if not re.fullmatch(r"\d{2}:\d{2}:\d{2}", timestamp):
        raise HTTPException(400, "Use an HH:MM:SS timestamp.")
    bookmark_id = uuid.uuid4().hex
    put_bookmark(bookmark_id, job_id, timestamp, note)
    return {"id": bookmark_id, "timestamp": timestamp, "note": note}


@app.delete("/api/jobs/{job_id}/bookmarks/{bookmark_id}")
def remove_bookmark(job_id: str, bookmark_id: str, request: Request) -> dict[str, str]:
    _owned_job(job_id, _owner(request))
    if not delete_bookmark(bookmark_id, job_id):
        raise HTTPException(404, "Bookmark not found.")
    return {"status": "deleted"}


@app.patch("/api/jobs/{job_id}/chapters/{chapter_index}")
def edit_chapter(job_id: str, chapter_index: int, request: Request, body: dict[str, str]) -> dict[str, Any]:
    job = _owned_job(job_id, _owner(request))
    result = job.get("result") or {}
    chapters = result.get("chapters", [])
    if chapter_index < 0 or chapter_index >= len(chapters):
        raise HTTPException(404, "Chapter not found.")
    title = (body.get("title") or "").strip()
    if not title or len(title) > 120:
        raise HTTPException(400, "Chapter title must contain 1 to 120 characters.")
    chapters[chapter_index]["title"] = title
    result["chapters"] = chapters
    db_update_job(job_id, result=result)
    return chapters[chapter_index]


@app.get("/api/jobs/{job_id}/chat")
def chat_history(job_id: str, request: Request) -> list[dict[str, Any]]:
    _owned_job(job_id, _owner(request))
    return get_chat_messages(job_id)


@app.post("/api/jobs/{job_id}/chat")
def chat(job_id: str, request: Request, body: dict[str, str]) -> dict[str, Any]:
    job = _owned_job(job_id, _owner(request))
    question = (body.get("question") or "").strip()
    if not question or len(question) > 2000:
        raise HTTPException(400, "Enter a question up to 2,000 characters.")
    owner = job["owner"]
    _limit_or_429(f"chat-minute:{owner}", CHAT_PER_MINUTE_LIMIT, 60, "Chat request limit reached. Wait a minute and try again.")
    job = _ensure_timestamp_index(job)
    normalized = " ".join(question.casefold().split())
    history = get_chat_messages(job_id)
    recent_history = history[-8:]
    history_key = json.dumps([(item.get("role"), item.get("content")) for item in recent_history], ensure_ascii=False)
    question_hash = hashlib.sha256(f"chat-v2|{normalized}|{history_key}".encode("utf-8")).hexdigest()
    cached = get_answer_cache(job_id, question_hash, configured_model())
    if cached:
        increment("rag_answer_cache_hits")
        answer, sources = cached["answer"], cached["sources"]
    else:
        if not job.get("collection_name"):
            raise HTTPException(409, "This analysis is not ready for chat.")
        try:
            sources = retrieve_sources(job["collection_name"], question, k=6)
            increment("rag_retrieval_requests")
            increment("rag_sources_returned", len(sources))
            logger.info("chat_retrieved job_id=%s source_count=%d", job_id, len(sources))
        except Exception:
            logger.exception("chat_retrieval_failed job_id=%s", job_id)
            sources = []
        try:
            answer = answer_from_sources(question, sources, recent_history)
        except Exception as exc:
            logger.exception("chat_answer_failed job_id=%s", job_id)
            if is_rate_limit_error(exc):
                raise HTTPException(429, "The language model is rate-limited. Wait briefly and try again.", headers={"Retry-After": "30"}) from exc
            raise HTTPException(502, f"Could not generate a chat answer: {str(exc)[:250]}") from exc
        if not any(marker in answer.lower() for marker in ("configuration error:", "currently rate-limited", "an error occurred")):
            save_answer_cache(job_id, question_hash, configured_model(), answer, sources)
    add_chat_message(job_id, "user", question)
    add_chat_message(job_id, "assistant", answer, sources)
    return {"answer": answer, "sources": sources}


@app.get("/api/jobs/{job_id}/study/{kind}")
def get_study(job_id: str, kind: str, request: Request) -> dict[str, Any] | None:
    _owned_job(job_id, _owner(request))
    if kind not in {"flashcards", "quiz", "terms"}:
        raise HTTPException(404, "Unknown study output.")
    if kind == "quiz":
        # Quiz questions and answer keys are intentionally not persisted.
        delete_study_set(job_id, "quiz")
        return None
    return get_study_set(job_id, kind)


def _quiz_transcript_sample(transcript: str, budget: int = 18000) -> str:
    if len(transcript) <= budget:
        return transcript
    rng = random.SystemRandom()
    windows = 6
    window_size = budget // windows
    samples = []
    for band in range(windows):
        low = len(transcript) * band // windows
        high = len(transcript) * (band + 1) // windows
        latest_start = max(low, high - window_size)
        start = rng.randint(low, latest_start) if latest_start > low else low
        if start > low:
            newline = transcript.find("\n", start, min(start + 240, high))
            if newline >= 0:
                start = newline + 1
        samples.append(transcript[start:min(high, start + window_size)])
    return "\n\n[OTHER TRANSCRIPT SECTION]\n\n".join(samples)


def _normalized_question(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _question_overlap(question: str, previous: list[str]) -> bool:
    tokens = set(_normalized_question(question).split()) - {"what", "which", "how", "why", "when", "where", "does", "is", "are", "the", "a", "an", "of", "in", "on", "to", "for", "and", "or", "it", "this", "that"}
    if not tokens:
        return any(_normalized_question(question) == _normalized_question(old) for old in previous)
    for old in previous:
        old_tokens = set(_normalized_question(old).split()) - {"what", "which", "how", "why", "when", "where", "does", "is", "are", "the", "a", "an", "of", "in", "on", "to", "for", "and", "or", "it", "this", "that"}
        if _normalized_question(question) == _normalized_question(old):
            return True
        if len(tokens | old_tokens) >= 4 and len(tokens & old_tokens) / max(1, len(tokens | old_tokens)) >= 0.72:
            return True
    return False


def _quiz_repeat_count(items: list[dict[str, Any]], previous: list[str]) -> int:
    lexical_repeats = [_question_overlap(item["question"], previous) for item in items]
    if not previous:
        return sum(lexical_repeats)
    try:
        from core.vector_store import get_embeddings
        vectors = get_embeddings().embed_documents(previous + [item["question"] for item in items])
        old_vectors, new_vectors = vectors[:len(previous)], vectors[len(previous):]
        for index, vector in enumerate(new_vectors):
            if lexical_repeats[index]:
                continue
            for old in old_vectors:
                denominator = (sum(value * value for value in vector) * sum(value * value for value in old)) ** 0.5
                similarity = sum(left * right for left, right in zip(vector, old)) / denominator if denominator else 0
                if similarity >= 0.82:
                    lexical_repeats[index] = True
                    break
    except Exception:
        logger.warning("quiz_semantic_overlap_check_unavailable", exc_info=True)
    return sum(lexical_repeats)


def _validate_quiz(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != 10:
        raise ValueError("The quiz model must return exactly ten questions.")
    validated = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("A quiz question was malformed.")
        question = str(item.get("question", "")).strip()
        choices = item.get("choices")
        answer_index = item.get("answer_index")
        if (not question or _normalized_question(question) in seen or not isinstance(choices, list)
                or len(choices) != 4 or not isinstance(answer_index, int) or not 0 <= answer_index < 4):
            raise ValueError("Quiz questions need unique wording, four options, and a valid answer key.")
        seen.add(_normalized_question(question))
        validated.append({"question": question, "choices": [str(choice) for choice in choices],
                          "answer_index": answer_index, "explanation": str(item.get("explanation", "")).strip()})
    return validated


def _parse_quiz_response(output: Any) -> dict[str, Any]:
    """Parse a model response without treating an empty completion as a JSON error."""
    text = output if isinstance(output, str) else str(output or "")
    text = text.strip()
    if not text:
        raise ValueError("The model returned an empty response.")
    try:
        payload = _extract_json(text)
    except (json.JSONDecodeError, ValueError, TypeError):
        # Some providers wrap otherwise valid JSON in markdown fences or add a
        # short preamble. Decode the first complete JSON object in that output.
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                payload, _ = decoder.raw_decode(text[index:])
                break
            except json.JSONDecodeError:
                continue
        else:
            raise ValueError("The model response did not contain a JSON quiz object.")
    if not isinstance(payload, dict):
        raise ValueError("The model response must be a JSON object.")
    return payload


@app.post("/api/jobs/{job_id}/study/{kind}")
def generate_study(job_id: str, kind: str, request: Request, body: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    job = _owned_job(job_id, _owner(request))
    if kind not in {"flashcards", "quiz", "terms"}:
        raise HTTPException(404, "Unknown study output.")
    if kind == "quiz":
        delete_study_set(job_id, "quiz")
    if kind != "quiz":
        cached = get_study_set(job_id, kind)
        if cached:
            increment("study_cache_hits")
            return cached
    _limit_or_429(f"chat-minute:{job['owner']}", CHAT_PER_MINUTE_LIMIT, 60, "AI request limit reached. Wait a minute and try again.")
    transcript = (job.get("result") or {}).get("transcript", "")
    if not transcript:
        raise HTTPException(409, "This analysis has no transcript to study.")
    # Quiz question sets are generated afresh and never saved in SQLite/cache.
    if kind == "quiz":
        excerpt = _quiz_transcript_sample(transcript)
        previous = body.get("previous_questions", []) if isinstance(body, dict) else []
        previous = [str(item)[:250] for item in previous if isinstance(item, str) and item.strip()][-100:]
        previous_text = "\n".join(f"- {item}" for item in previous) or "None yet."
        schema = '{"items":[{"question":"...","choices":["...","...","...","..."],"answer_index":0,"explanation":"..."}]}'
        prompt = (
            "Create exactly 10 high-quality four-option MCQs using only facts taught in the transcript excerpts. "
            "Cover different concepts and sections; mix understanding, application, and careful recall. "
            "Use plausible distractors, one unambiguous correct answer, vary the correct option position, and do not use 'all/none of the above'. "
            "Do not repeat or paraphrase prior questions below. At most two questions may test the same underlying idea as prior questions; aim for zero overlap. "
            "Add a brief explanation grounded in the transcript. Return only valid JSON matching this schema: " + schema
            + "\nPREVIOUSLY ASKED QUESTIONS (avoid these):\n" + previous_text
            + "\nTRANSCRIPT EXCERPTS:\n" + excerpt
        )
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate
        chain = ChatPromptTemplate.from_messages([
            ("system", "You are an assessment writer. Be accurate, varied, and strictly grounded in the supplied transcript. Return only valid JSON."),
            ("human", "{prompt}"),
        ]) | get_llm(temperature=0.65) | StrOutputParser()
        try:
            # Retry once when the provider returns a blank/truncated/non-JSON
            # completion. Keep the transcript and questions ephemeral.
            last_error: Exception | None = None
            items: list[dict[str, Any]] | None = None
            for attempt in range(2):
                attempt_prompt = prompt if attempt == 0 else (
                    prompt + "\nIMPORTANT: Your previous completion was empty or invalid. "
                    "Regenerate the complete ten-question quiz now. Output one valid JSON object only; "
                    "do not include markdown, commentary, or code fences."
                )
                try:
                    output = invoke_with_retry(chain, {"prompt": attempt_prompt}, label="study_quiz" if attempt == 0 else "study_quiz_format_retry")
                    items = _validate_quiz(_parse_quiz_response(output))
                    break
                except (ValueError, json.JSONDecodeError) as exc:
                    last_error = exc
                    logger.warning("quiz_invalid_completion job_id=%s attempt=%d", job_id, attempt + 1)
            if items is None:
                raise ValueError(str(last_error or "The model returned an invalid quiz."))
            overlaps = _quiz_repeat_count(items, previous)
            if overlaps > 2:
                retry_prompt = prompt + "\nYour last draft repeated too many previous ideas. Regenerate the full set with different concepts and question angles."
                output = invoke_with_retry(chain, {"prompt": retry_prompt}, label="study_quiz_diversity_retry")
                items = _validate_quiz(_parse_quiz_response(output))
                if _quiz_repeat_count(items, previous) > 2:
                    raise ValueError("The generated set overlapped too much with recent questions. Generate again for a fresh set.")
            increment("quiz_sets_generated")
            return {"items": items, "persisted": False, "set_id": uuid.uuid4().hex}
        except Exception as exc:
            logger.warning("quiz_generation_failed job_id=%s error=%s", job_id, str(exc)[:200])
            if is_rate_limit_error(exc):
                raise HTTPException(429, "The quiz provider is rate-limited. Wait briefly and try again.", headers={"Retry-After": "30"}) from exc
            raise HTTPException(502, f"Could not generate a fresh quiz. {str(exc)[:220]} Check your model/API configuration and try again.") from exc

    # Keep flashcard and term prompts small with a spread across long videos.
    if len(transcript) <= 18000:
        excerpt = transcript
    else:
        window = 6000
        middle = max(0, (len(transcript) - window) // 2)
        excerpt = "\n[BEGINNING]\n" + transcript[:window] + "\n[MIDDLE]\n" + transcript[middle:middle + window] + "\n[ENDING]\n" + transcript[-window:]
    schemas = {
        "flashcards": '{"items":[{"front":"question","back":"answer"}]}',
        "quiz": '{"items":[{"question":"...","choices":["...","...","...","..."],"answer_index":0,"explanation":"..."}]}',
        "terms": '{"items":[{"term":"...","definition":"..."}]}',
    }
    prompt = f"Create 8 {kind} from only this transcript. Do not invent facts. Return JSON matching this schema: {schemas[kind]}\nTRANSCRIPT:\n{excerpt}"
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    chain = ChatPromptTemplate.from_messages([("system", "You create accurate study material from video transcripts. Return only valid JSON."), ("human", "{prompt}")]) | get_llm(temperature=0.2) | StrOutputParser()
    try:
        output = invoke_with_retry(chain, {"prompt": prompt}, label=f"study_{kind}")
        payload = _extract_json(output)
        if not isinstance(payload.get("items"), list):
            raise ValueError("Study response did not contain items.")
    except Exception as exc:
        raise HTTPException(502, f"Could not generate study material: {str(exc)[:300]}")
    save_study_set(job_id, kind, payload)
    return payload


def _pdf_transcript_groups(transcript: str, chapters: list[dict[str, Any]]) -> list[tuple[str, str]]:
    marker_re = re.compile(r"\[(?:Speech timestamp |Approx\. timestamp )(\d{2}:\d{2}:\d{2})\]\s*")
    markers = list(marker_re.finditer(transcript))
    if not markers:
        return [("Transcript", transcript)] if transcript.strip() else []
    chapter_titles = {}
    for chapter in chapters:
        stamp = chapter.get("timestamp", "00:00:00")
        hours, minutes, seconds = (int(part) for part in stamp.split(":"))
        chapter_titles[(hours * 3600 + minutes * 60 + seconds) // 600] = chapter.get("title", "")
    groups: dict[int, list[str]] = {}
    labels: dict[int, str] = {}
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(transcript)
        body = transcript[marker.end():end].strip()
        if not body:
            continue
        hours, minutes, seconds = (int(part) for part in marker.group(1).split(":"))
        window = (hours * 3600 + minutes * 60 + seconds) // 600
        groups.setdefault(window, []).append(body)
        labels.setdefault(window, chapter_titles.get(window) or f"Topic from {marker.group(1)}")
    return [(labels[key], "\n".join(groups[key])) for key in sorted(groups)]


def _pdf_review_questions(job: dict[str, Any]) -> list[dict[str, str]]:
    transcript = (job.get("result") or {}).get("transcript", "")
    if not transcript:
        return []
    prompt = (
        "Create 8 useful study questions with concise answers from the supplied video transcript. "
        "Cover different topics, explain key ideas, and do not add facts absent from the transcript. "
        'Return only JSON: {"items":[{"question":"...","answer":"..."}]}\nTRANSCRIPT:\n'
        + _quiz_transcript_sample(transcript)
    )
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    chain = ChatPromptTemplate.from_messages([
        ("system", "You write accurate video study notes. Return only valid JSON."),
        ("human", "{prompt}"),
    ]) | get_llm(temperature=0.45) | StrOutputParser()
    try:
        payload = _extract_json(invoke_with_retry(chain, {"prompt": prompt}, label="pdf_review_questions"))
        items = payload.get("items", [])
        return [{"question": str(item.get("question", "")).strip(), "answer": str(item.get("answer", "")).strip()}
                for item in items if isinstance(item, dict) and item.get("question") and item.get("answer")][:8]
    except Exception:
        logger.exception("pdf_question_generation_failed job_id=%s", job["id"])
        return []


@app.get("/api/jobs/{job_id}/export/pdf")
def export_pdf(job_id: str, request: Request) -> Response:
    job = _owned_job(job_id, _owner(request))
    if job["state"] != "complete":
        raise HTTPException(409, "Only completed analyses can be exported.")
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer
    except ImportError as exc:
        raise HTTPException(503, "Install reportlab with: python -m pip install reportlab") from exc

    from html import escape
    from io import BytesIO

    result = job.get("result") or {}
    output = BytesIO()
    styles = getSampleStyleSheet()
    regular, bold = "Helvetica", "Helvetica-Bold"
    font_candidates = [
        (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
    ]
    for regular_file, bold_file in font_candidates:
        if regular_file.is_file() and bold_file.is_file():
            try:
                pdfmetrics.registerFont(TTFont("FrameSutra", str(regular_file)))
                pdfmetrics.registerFont(TTFont("FrameSutra-Bold", str(bold_file)))
                regular, bold = "FrameSutra", "FrameSutra-Bold"
                break
            except Exception:
                continue

    navy = colors.HexColor("#17264A")
    blue = colors.HexColor("#5264E8")
    pale = colors.HexColor("#EEF1FF")
    ink = colors.HexColor("#34415C")
    muted = colors.HexColor("#738097")
    title_style = ParagraphStyle("VideoTitle", parent=styles["Title"], fontName=bold, fontSize=25, leading=31, textColor=navy, spaceAfter=10)
    h1 = ParagraphStyle("VideoH1", parent=styles["Heading1"], fontName=bold, fontSize=16, leading=21, textColor=navy, spaceBefore=15, spaceAfter=7)
    h2 = ParagraphStyle("VideoH2", parent=styles["Heading2"], fontName=bold, fontSize=11, leading=15, textColor=blue, spaceBefore=9, spaceAfter=4)
    body_style = ParagraphStyle("VideoBody", parent=styles["BodyText"], fontName=regular, fontSize=9, leading=14, textColor=ink, spaceAfter=6)
    small_style = ParagraphStyle("VideoSmall", parent=body_style, fontSize=8, leading=12, textColor=muted)
    centered = ParagraphStyle("VideoCenter", parent=title_style, alignment=TA_CENTER)

    def paragraph(text: Any, style=body_style) -> Paragraph:
        value = str(text or "")
        try:
            value.encode("latin-1")
        except UnicodeEncodeError:
            if regular == "Helvetica":
                value = value.encode("cp1252", "replace").decode("cp1252")
        safe = escape(value).replace("\n", "<br/>")
        return Paragraph(safe, style)

    def on_page(canvas, doc):
        canvas.saveState()
        page_width, page_height = letter
        canvas.setFillColor(navy)
        canvas.rect(0, page_height - 64, page_width, 64, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#8DE3E0"))
        canvas.rect(0, page_height - 66, page_width, 2, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont(bold, 10)
        canvas.drawString(42, page_height - 31, "FRAMESUTRA  /  VIDEO NOTES")
        canvas.setFont(regular, 8)
        canvas.drawRightString(page_width - 42, page_height - 31, (result.get("title") or "Analysis")[:48])
        canvas.setFillColor(muted)
        canvas.setFont(regular, 8)
        canvas.drawString(42, 27, "Generated from the transcript and saved analysis")
        canvas.drawRightString(page_width - 42, 27, f"{doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(output, pagesize=letter, rightMargin=46, leftMargin=46, topMargin=87, bottomMargin=45,
                            title=str(result.get("title") or "FrameSutra Notes"), author="FrameSutra")
    story = [Spacer(1, 12), paragraph(result.get("title") or "Video notes", title_style),
             paragraph(f"Source: {result.get('source', 'Unknown')}<br/>Language: {result.get('language', 'English')}<br/>Created: {job.get('created_at', '')[:10]}", small_style),
             Spacer(1, 10), HRFlowable(width="100%", thickness=1, color=pale), paragraph("Video overview", h1),
             paragraph(result.get("summary") or "No summary available.")]
    for heading, field in (("Action items", "action_items"), ("Key decisions", "key_decisions"), ("Open questions", "open_questions")):
        value = result.get(field)
        if value:
            story.extend([paragraph(heading, h2), paragraph(value)])

    try:
        _limit_or_429(f"chat-minute:{job['owner']}", CHAT_PER_MINUTE_LIMIT, 60, "AI request limit reached. PDF will use saved chat answers where available.")
        qa_items = _pdf_review_questions(job)
    except HTTPException as exc:
        if exc.status_code != 429:
            raise
        qa_items = []
    saved_chat = get_chat_messages(job_id)
    story.append(paragraph("Review questions and answers", h1))
    if qa_items:
        story.append(paragraph("AI-generated from the transcript for this PDF. These questions and answers are not saved to the analysis database.", small_style))
        for index, item in enumerate(qa_items, 1):
            story.append(KeepTogether([paragraph(f"{index}. {item['question']}", h2), paragraph(item["answer"])]))
    elif saved_chat:
        for item in saved_chat:
            if item["role"] == "user":
                story.append(paragraph(f"Question: {item['content']}", h2))
            elif item["role"] == "assistant":
                story.append(paragraph(f"Answer: {item['content']}"))
    else:
        story.append(paragraph("No review questions could be generated. The full transcript is included below.", small_style))

    chapters = (result.get("chapters") or [])
    story.append(paragraph("Topic notes and full transcript", h1))
    for heading, content in _pdf_transcript_groups(result.get("transcript", ""), chapters):
        story.extend([paragraph(heading, h2), paragraph(content)])
    if result.get("visual_evidence"):
        story.append(paragraph("Visual notes", h1))
        for item in result["visual_evidence"]:
            story.append(KeepTogether([paragraph(f"Frame near {item.get('timestamp', 'unknown')}", h2), paragraph(item.get("description", ""))]))
    marks = get_bookmarks(job_id)
    if marks:
        story.append(paragraph("Bookmarks and notes", h1))
        for item in marks:
            story.append(paragraph(f"{item['timestamp']}  {item['note']}"))
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return Response(output.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="framesutra-notes-{job_id[:8]}.pdf"'})


@app.delete("/api/cache")
def clear_cache(request: Request, body: dict[str, bool]) -> dict[str, int]:
    if not body.get("confirm"):
        raise HTTPException(400, "Confirm cache deletion.")
    if count_jobs(("queued", "running")):
        raise HTTPException(409, "Wait until active jobs finish before clearing caches.")
    cleared = 0
    for name in ("transcripts", "analysis", "analysis_results", "sarvam_pieces", "visual"):
        root = PROJECT_ROOT / ".cache" / name
        if root.exists():
            cleared += sum(1 for item in root.rglob("*") if item.is_file())
            shutil.rmtree(root, ignore_errors=True)
    audio_cache = PROJECT_ROOT / "downloads" / "youtube_audio_cache"
    if audio_cache.exists():
        cleared += sum(1 for item in audio_cache.rglob("*") if item.is_file())
        shutil.rmtree(audio_cache, ignore_errors=True)
    frame_cache = PROJECT_ROOT / "downloads" / "frames"
    if frame_cache.exists():
        cleared += sum(1 for item in frame_cache.rglob("*") if item.is_file())
        shutil.rmtree(frame_cache, ignore_errors=True)
    increment("cache_clears")
    logger.info("cache_cleared owner=%s files=%d", _owner(request), cleared)
    return {"cleared_files": cleared}


@app.post("/api/maintenance/cleanup")
def manual_cleanup(request: Request) -> dict[str, int]:
    logger.info("manual_cleanup owner=%s", _owner(request))
    return run_cleanup()
