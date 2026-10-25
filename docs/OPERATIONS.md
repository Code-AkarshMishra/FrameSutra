# Configuration and operations

This guide covers local development and maintenance. Begin with the [README quick start](../README.md#quick-start).

## Configuration reference

Copy `.env.example` to `.env`, then set the credentials required by the features you plan to use. The project root is resolved from the Python source location, so `.env` does not depend on the current terminal directory.

| Variable | Example/default | Required? | Purpose |
|---|---|---|---|
| `GROQ_API_KEY` | Empty in example | Yes for analysis/chat/study | Groq text generation and PDF review questions |
| `GROQ_MODEL` | Example: `llama-3.1-8b-instant`; runtime fallback is `openai/gpt-oss-20b` | Optional override | Text model ID. Legacy IDs have a compatibility mapping in `core/llm_provider.py`; verify current availability with your provider account. |
| `GROQ_VISION_MODEL` | `meta-llama/llama-4-scout-17b-16e-instruct` | Only for optional visuals | Vision model ID; availability depends on provider account. |
| `SARVAM_API_KEY` | Empty in example | Only for Hinglish | Sarvam speech-to-text/translation authorization |
| `SARVAM_STT_MODEL` | `saaras:v2.5` | Optional override | Sarvam transcription/translation model |
| `WHISPER_MODEL` | `small` | Optional override | Local Whisper model size/name; larger models need more time, memory, and download space. |
| `VIDEO_JOB_WORKERS` | `1` | No | In-process job worker count; keep one API process. |
| `MAX_OUTSTANDING_JOBS` | `3` | No | Maximum queued plus active jobs |
| `MAX_UPLOAD_MB` | `512` | No | Upload byte limit in MiB |
| `MAX_MEDIA_HOURS` | `6` | No | Maximum source duration |
| `JOB_HOURLY_LIMIT` | `5` | No | Submission limit per client identity per hour |
| `CHAT_PER_MINUTE_LIMIT` | `15` | No | Chat/study request limit per minute |
| `JOB_RETENTION_DAYS` | `30` | No | Age before unsaved job records expire; saved jobs are retained |
| `MEDIA_RETENTION_DAYS` | `7` | No | Age before media cleanup |
| `FRONTEND_ORIGINS` | Localhost and 127.0.0.1 Vite origins | No | CORS allowed origins for the API |

Environment variables are read by the running process. Restart the API after editing `.env`. Never place real secrets in `.env.example`, logs, issues, or screenshots.

## Local run commands

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r Requirements.txt
Copy-Item .env.example .env
```

Edit `.env`, then use two terminals:

```powershell
# Terminal 1, project root
.\.venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```

```powershell
# Terminal 2
cd frontend
npm install
npm run dev
```

### macOS/Linux shell

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r Requirements.txt
cp .env.example .env
# Edit .env, then in separate terminals:
python -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload
cd frontend && npm install && npm run dev
```

### Native tools and first-run downloads

Install FFmpeg and ffprobe and ensure both resolve from the backend process. They are used for media conversion, duration probing, and visual frame extraction. The Python packages do not bundle FFmpeg executables.

Whisper and sentence-transformer model weights may download on first use. Allow disk space and network access. The first transcription/index may take substantially longer than later runs. YouTube access and supported formats can change; download success is not guaranteed for every link.

## Backup and full reset

The job store currently uses the legacy filename `videolens.sqlite3` so existing local data remains accessible after the FrameSutra rebrand.

### Back up

1. Stop the API first so SQLite is closed and no job is writing files.
2. Copy `videolens.sqlite3` together with any `videolens.sqlite3-wal` and `videolens.sqlite3-shm` files that exist.
3. Copy `vector_db/` and any uploads/media you explicitly want to preserve.
4. Protect the backup as sensitive data; it may include transcripts, chats, private media, and embeddings.

Restoring only the database without its corresponding vector index or media may leave analyses that refer to missing assets.

### Full reset

1. Stop both the API and frontend processes.
2. Export or back up anything you want to keep.
3. Remove `videolens.sqlite3`, its `-wal` and `-shm` files, and generated contents of `uploads/`, `downloads/`, `vector_db/`, and `.cache/`.
4. Restart the services. The API recreates its database schema and required working folders.

Do not remove `.env` if you want to keep provider configuration. Do not remove `.venv` or `frontend/node_modules` for a data reset; those contain installed dependencies, not user analyses. Model caches may be stored outside the project and are not necessarily removed by this procedure.

## Troubleshooting

<details>
<summary><strong>The page says the API cannot be reached</strong></summary>

- Confirm Uvicorn is running on port 8000 and `/api/health` responds.
- Check the Vite `/api` proxy in `frontend/vite.config.js` and avoid changing the API host without updating it.
- Check firewall/proxy settings and look at the API terminal for startup exceptions.
</details>

<details>
<summary><strong>Analysis returns a missing-key or provider error</strong></summary>

- Confirm `GROQ_API_KEY` is present in root `.env` and restart the API.
- Hinglish requires `SARVAM_API_KEY` as well.
- Verify configured model IDs and account access. Model availability, account limits, and provider rules can change.
- HTTP 429 usually indicates a local admission limit or provider rate limit; wait and retry after the limit window.
</details>

<details>
<summary><strong>Upload, conversion, or visual analysis fails</strong></summary>

- Confirm FFmpeg and ffprobe are available in the environment used by Uvicorn.
- Check upload size and duration against configured limits and available disk space.
- The visual option requires a local video, not an audio file or YouTube source. Confirm `GROQ_VISION_MODEL` availability.
- Inspect the API logs for the failing stage and preserve its job ID when diagnosing.
</details>

<details>
<summary><strong>First run is very slow or memory intensive</strong></summary>

- Whisper and embedding model weights may be downloading or loading.
- The default Whisper model is `small`; smaller models reduce resource needs at the cost of quality.
- Reduce input duration, close other heavy workloads, and ensure disk space is available for model and vector data.
</details>

<details>
<summary><strong>YouTube audio cannot be prepared</strong></summary>

YouTube player behavior, availability, privacy settings, region rules, and downloader compatibility can affect acquisition. Confirm the URL is a supported public video, update dependencies when appropriate, and check `yt-dlp` output. Use an authorized local media file if downloading is unavailable.
</details>

<details>
<summary><strong>Some results have rough timestamps</strong></summary>

Word-level timestamps are not implemented. English jobs use Whisper speech-segment starts when available; Hinglish and older records use approximate chunk markers. Refresh timestamps is offered for eligible English results only when retained audio exists.
</details>

## Build and local checks

Create a production frontend bundle with:

```bash
cd frontend
npm run build
```

The output is written to `frontend/dist/` and ignored by Git. This command verifies that Vite can compile the frontend; it does not validate provider credentials, media processing, or production hosting.

## Generated data and Git hygiene

The repository’s `.gitignore` excludes `.env`, virtual environments, media, uploads, caches, vector data, SQLite files, `frontend/node_modules`, and `frontend/dist`. Keep those entries intact unless a deployment workflow intentionally handles these assets another way.
