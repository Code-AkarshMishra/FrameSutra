import whisper
import os
import requests
from pydub import AudioSegment
from core.config import load_project_env
from core.observability import increment
import logging

load_project_env()

# Sarvam's sync STT-translate API rejects audio longer than 30s.
# We slice each chunk into 25s pieces (with a 5s safety margin) before sending.
SARVAM_PIECE_SECONDS = 25


WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small").strip() or "small"


SARVAM_STT_TRANSLATE_URL = "https://api.sarvam.ai/speech-to-text-translate"
SARVAM_MODEL = os.getenv("SARVAM_STT_MODEL", "saaras:v2.5").strip() or "saaras:v2.5"

_model = None


def load_model():

    global _model  

    if _model is None: 
        print(f"Loading Whisper model: {WHISPER_MODEL} ...")
        _model = whisper.load_model(WHISPER_MODEL) 
        print("Whisper model loaded.")
    return _model 


def transcribe_chunk_whisper(chunk_path: str, language: str = "english") -> str:
    """Run local Whisper; explicitly select English when English mode is chosen."""
    model = load_model()
    options = {"task": "transcribe", "fp16": False}
    if language.lower() == "english":
        options["language"] = "en"
    result = model.transcribe(chunk_path, **options)
    return result["text"].strip()


def transcribe_chunk_whisper_timed(chunk_path: str, language: str = "english") -> dict:
    """Return Whisper's segment-level times so citations can jump near the speech."""
    model = load_model()
    options = {"task": "transcribe", "fp16": False}
    if language.lower() == "english":
        options["language"] = "en"
    result = model.transcribe(chunk_path, **options)
    segments = [
        {"start": max(0.0, float(item.get("start", 0))), "text": str(item.get("text", "")).strip()}
        for item in result.get("segments", []) if str(item.get("text", "")).strip()
    ]
    return {"text": str(result.get("text", "")).strip(), "segments": segments}


def _send_to_sarvam(piece_path: str) -> str:
    """Send one ≤30s WAV file to Sarvam and return the English transcript."""
    sarvam_api_key = os.getenv("SARVAM_API_KEY")
    if not sarvam_api_key:
        raise RuntimeError("SARVAM_API_KEY is not set in environment / .env")

    headers = {"api-subscription-key": sarvam_api_key}

    with open(piece_path, "rb") as f:
        files = {"file": (os.path.basename(piece_path), f, "audio/wav")}
        data = {"model": SARVAM_MODEL, "with_diarization": "false"}
        response = requests.post(
            SARVAM_STT_TRANSLATE_URL,
            headers=headers,
            files=files,
            data=data,
            timeout=120,
        )
    increment("sarvam_calls")
    if response.status_code == 429:
        increment("sarvam_rate_limits")

    if not response.ok:
        print(f"\n❌ Sarvam returned {response.status_code}")
        print(f"Response body: {response.text}\n")
        response.raise_for_status()

    return response.json().get("transcript", "")


def transcribe_chunk_sarvam(chunk_path: str) -> str:
    """
    Sarvam sync API only accepts ≤30s audio. We split this chunk into
    25-second pieces, send each separately, and join the transcripts.
    """
    if not os.getenv("SARVAM_API_KEY"):
        raise RuntimeError("SARVAM_API_KEY is not set in environment / .env")

    audio = AudioSegment.from_wav(chunk_path)
    piece_ms = SARVAM_PIECE_SECONDS * 1000

    import hashlib
    import json
    from pathlib import Path
    from core.config import PROJECT_ROOT

    full_text_parts = []
    total_pieces = (len(audio) + piece_ms - 1) // piece_ms
    cache_dir = PROJECT_ROOT / ".cache" / "sarvam_pieces"
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        stat = os.stat(chunk_path)
        signature = f"{os.path.abspath(chunk_path)}|{stat.st_size}|{stat.st_mtime_ns}"
    except OSError:
        signature = os.path.abspath(chunk_path)
    cache_key = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:24]
    cache_file = cache_dir / f"{cache_key}.json"
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    except (OSError, json.JSONDecodeError):
        cache = {}

    for i, start in enumerate(range(0, len(audio), piece_ms)):
        if str(i) in cache:
            full_text_parts.append(cache[str(i)])
            print(f"  → Reusing Sarvam piece checkpoint {i + 1}/{total_pieces}")
            continue
        piece = audio[start: start + piece_ms]
        piece_path = f"{chunk_path}_sv_{i}.wav"
        piece.export(piece_path, format="wav")
        try:
            print(f"  → Sarvam piece {i + 1}/{total_pieces} ...")
            piece_text = _send_to_sarvam(piece_path)
            full_text_parts.append(piece_text)
            cache[str(i)] = piece_text
            tmp = cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            tmp.replace(cache_file)
        finally:
            if os.path.exists(piece_path):
                os.remove(piece_path)

    return " ".join(full_text_parts).strip()

   



def transcribe_chunk(chunk_path: str, language: str = "english") -> str:
    """
    Route one chunk to Whisper or Sarvam depending on language choice.
    - english  → Whisper (local model)
    - hinglish → Sarvam (translates to English while transcribing)
    """
    if language.lower() == "hinglish":
        return transcribe_chunk_sarvam(chunk_path)
    return transcribe_chunk_whisper(chunk_path, language=language)


def _format_timestamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def transcribe_all(
    chunks: list,
    language: str = "english",
    source_id: str | None = None,
    progress_callback=None,
) -> str:
    """
    Transcribe audio chunks with durable per-chunk checkpoints.

    Checkpoints are keyed by source identity + language + chunk index. Whisper
    segment timestamps are speech-aligned; Sarvam currently has only coarse
    ten-minute chunk timestamps in this pipeline.
    """
    import hashlib
    import json
    from pathlib import Path
    from core.config import PROJECT_ROOT

    engine = "Sarvam AI" if language.lower() == "hinglish" else "Whisper"
    print(f"Using {engine} for transcription.")

    cache_dir = PROJECT_ROOT / ".cache" / "transcripts"
    cache_dir.mkdir(parents=True, exist_ok=True)
    identity = source_id or "|".join(str(p) for p in chunks)
    # Include local source size/mtime when available so replacing a file at the
    # same path does not silently reuse an unrelated transcript.
    try:
        source_path = Path(identity)
        if source_path.is_file():
            source_stat = source_path.stat()
            identity = f"{identity}|{source_stat.st_size}|{source_stat.st_mtime_ns}"
    except (OSError, TypeError):
        pass
    model_identity = SARVAM_MODEL if language.lower() == "hinglish" else WHISPER_MODEL
    cache_key = hashlib.sha256(f"timestamped-v2|{identity}|{language.lower()}|{model_identity}".encode("utf-8")).hexdigest()[:24]
    cache_file = cache_dir / f"{cache_key}.json"

    try:
        checkpoint = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    except (OSError, json.JSONDecodeError):
        checkpoint = {}

    results = checkpoint.get("chunks", {})
    chunk_duration_seconds = 10 * 60

    for i, chunk in enumerate(chunks):
        key = str(i)
        if key in results and results[key].get("text") is not None:
            text = results[key]["text"]
            increment("transcript_chunk_cache_hits")
            logging.getLogger("framesutra.cache").info("transcript_chunk_cache_hit source_hash=%s chunk=%d", cache_key, i)
            print(f"Reusing transcript checkpoint {i + 1}/{len(chunks)}")
        else:
            print(f"Transcribing chunk {i + 1}/{len(chunks)}...")
            if language.lower() == "hinglish":
                text = transcribe_chunk_sarvam(chunk).strip()
                results[key] = {"text": text}
            else:
                timed = transcribe_chunk_whisper_timed(chunk, language=language)
                text = timed["text"]
                results[key] = {"text": text, "segments": timed["segments"]}
            checkpoint = {
                "source_id_hash": cache_key,
                "language": language.lower(),
                "chunks": results,
            }
            tmp = cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8")
            tmp.replace(cache_file)

        if progress_callback:
            progress_callback(i + 1, len(chunks))

    # Whisper supplies speech-aligned segment times relative to each 10-minute
    # audio chunk. Sarvam does not, so its transcript keeps the coarse start time.
    pieces = []
    for i in range(len(chunks)):
        item = results.get(str(i), {})
        text = item.get("text", "").strip()
        segments = item.get("segments") or []
        if segments:
            for segment in segments:
                segment_text = str(segment.get("text", "")).strip()
                if segment_text:
                    stamp = _format_timestamp(i * chunk_duration_seconds + float(segment.get("start", 0)))
                    pieces.append(f"[Speech timestamp {stamp}]\n{segment_text}")
        elif text:
            stamp = _format_timestamp(i * chunk_duration_seconds)
            pieces.append(f"[Approx. timestamp {stamp}]\n{text}")

    print("Transcription complete.")
    return "\n\n".join(pieces)
